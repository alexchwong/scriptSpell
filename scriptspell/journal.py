"""Local revision sessions shared by headless callers and the browser playground."""
import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from threading import RLock
from uuid import uuid4

from .codec import pack, unpack
from .profile import Limits
from .workflow import (AuthoringError, _guidance, _legacy_settings, correct_expected, edit_example, generate_draft,
                       improve_python, json_display_value, run_examples)


_MAX_METADATA_INTEGER = 2**53 - 1


def _settings_metadata(settings):
    if settings is None:
        return None
    safe = {}
    model = settings.get('model')
    if type(model) is str and len(model) <= 256 and model.strip():
        safe['model'] = model
    for field in ('temperature', 'reasoning', 'max_tokens'):
        if field not in settings:
            continue
        value = settings[field]
        if value is None:
            safe[field] = None
        elif field == 'temperature' and type(value) in (int, float) and abs(value) <= _MAX_METADATA_INTEGER:
            safe[field] = value
        elif field == 'reasoning' and type(value) is str and value in ('off', 'low', 'medium', 'high'):
            safe[field] = value
        elif field == 'max_tokens' and type(value) is int and 1 <= value <= _MAX_METADATA_INTEGER:
            safe[field] = value
    return safe or None


def _requested_metadata(settings, requested_settings):
    if requested_settings is None:
        requested_settings = _legacy_settings(settings)
    return _settings_metadata(requested_settings)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _encode_reports(reports):
    encoded = deepcopy(reports)
    for report in encoded:
        if 'actual' in report:
            report['actual'] = pack(report['actual'], Limits())
    return encoded


def _decode_reports(reports):
    decoded = deepcopy(reports)
    for report in decoded:
        if 'actual' in report:
            report['actual'] = unpack(report['actual'])
    return decoded


def _status(reports):
    if not reports or all(r['outcome'] == 'cancelled' for r in reports):
        return 'untested'
    if any(r['status'] == 'error' for r in reports):
        return 'error'
    return 'failing' if any(r['status'] == 'mismatch' for r in reports) else 'passing'


def _latest_test(data, revision_id):
    tests = data['tests'].get(revision_id)
    return tests[-1] if tests else None


def _latest_reports(data, revision_id):
    test = _latest_test(data, revision_id)
    return test['reports'] if test else []


def _record_test(data, revision_id, reports, attempt_id=None):
    data['tests'].setdefault(revision_id, []).append(dict(
        id=uuid4().hex, timestamp=_now(), attempt_id=attempt_id, reports=reports))


def _atomic_json(path, document):
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=True, allow_nan=False, default=json_display_value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class AuthoringSession:
    """Serialize edits and persist immutable draft revisions with separate test records."""

    def __init__(self, root='runs'):
        self.session_id = uuid4().hex
        self.directory = Path(root).resolve() / self.session_id
        self._lock = RLock()
        self._data = dict(format_version=1, session_id=self.session_id, active_id=None,
                          revisions={}, attempts={}, tests={})

    def _write(self, data):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _atomic_json(self.directory / 'journal.json', data)
        self._data = data

    def _check_active(self, revision_id):
        if revision_id != self._data['active_id']:
            raise AuthoringError('stale_revision')

    def _revision(self, revision_id):
        if type(revision_id) is not str or revision_id not in self._data['revisions']:
            raise AuthoringError('unknown_revision')
        return self._data['revisions'][revision_id]

    def _record_revision(self, data, draft, action, *, guidance='', settings=None,
                         attempt_id=None, restored_from=None, reports=None):
        revision_id = uuid4().hex
        data['revisions'][revision_id] = dict(
            id=revision_id, parent_id=data['active_id'], action=action, timestamp=_now(),
            guidance=guidance, requested_settings=settings, attempt_id=attempt_id,
            restored_from=restored_from, draft=draft)
        data['active_id'] = revision_id
        if reports is not None:
            _record_test(data, revision_id, reports, attempt_id)
        for attempt in data['attempts'].values():
            if attempt['status'] == 'pending':
                attempt['status'] = 'stale'
        return revision_id

    def snapshot(self, revision_id=None):
        """Return detached revision/attempt summaries and the selected revision with typed results."""
        with self._lock:
            data = self._data
            selected = data['active_id'] if revision_id is None else revision_id
            revision = self._revision(selected) if selected is not None else None
            summaries = [
                dict({k: v for k, v in entry.items() if k != 'draft'},
                     test_status=_status(_latest_reports(data, entry['id'])))
                for entry in data['revisions'].values()]
            attempts = [{k: v for k, v in entry.items() if k not in ('candidate', 'reports')}
                        for entry in data['attempts'].values()]
            return dict(active_id=data['active_id'], revision=deepcopy(revision),
                        revisions=deepcopy(summaries), attempts=deepcopy(attempts),
                        reports=_decode_reports(_latest_reports(data, selected)))

    def attempt(self, attempt_id):
        with self._lock:
            if type(attempt_id) is not str or attempt_id not in self._data['attempts']:
                raise AuthoringError('unknown_attempt')
            attempt = self._data['attempts'][attempt_id]
            return dict(deepcopy(attempt), reports=_decode_reports(attempt.get('reports', [])))

    def _try_model(self, action, settings, guidance, operation, *, selection=None, basis_test=None):
        # Called under the session lock. Store only safe error codes, never raw provider responses.
        original = self._data
        data = deepcopy(original)
        attempt_id = uuid4().hex
        entry = data['attempts'][attempt_id] = dict(
            id=attempt_id, revision_id=data['active_id'], action=action, timestamp=_now(),
            guidance=guidance, requested_settings=settings)
        entry.update(selection or {})
        if basis_test is not None:
            entry['basis_test_id'] = basis_test['id']
        try:
            candidate, reports = operation()
        except Exception as exc:
            entry.update(status='failed', error=exc.code if isinstance(exc, AuthoringError) else type(exc).__name__)
            if self._data is original:
                self._write(data)
            raise
        if self._data is not original:
            raise AuthoringError('stale_revision')
        entry.update(status='pending', candidate=candidate)
        if reports is not None:
            entry['reports'] = _encode_reports(reports)
            passing = {r['example_id'] for r in basis_test['reports'] if r['status'] == 'pass'}
            entry['regressions'] = [r['example_id'] for r in reports
                                    if r['example_id'] in passing and r['status'] != 'pass']
        if action == 'generate':
            entry.update(status='accepted')
            entry['accepted_revision_id'] = self._record_revision(
                data, entry.pop('candidate'), action, settings=settings, attempt_id=attempt_id)
        self._write(data)
        return attempt_id

    def generate(self, revision_id, dispatch, settings, instruction, *, requested_settings=None, **options):
        with self._lock:
            self._check_active(revision_id)
            metadata = _requested_metadata(settings, requested_settings)
            attempt_id = self._try_model('generate', metadata, '', lambda: (
                generate_draft(dispatch, settings, instruction, **options), None))
            return self._data['attempts'][attempt_id]['accepted_revision_id']

    def record_authored(self, revision_id, draft, *, staged=False, settings=None, action=None):
        """Store a draft already validated by an authoring workflow."""
        with self._lock:
            self._check_active(revision_id)
            data = deepcopy(self._data)
            active = self._record_revision(data, deepcopy(draft),
                                           action or ('staged' if staged else 'paste'),
                                           settings=_settings_metadata(settings))
            self._write(data)
            return active

    def run(self, revision_id, *, cancel=None):
        with self._lock:
            self._check_active(revision_id)
            reports = run_examples(self._revision(revision_id)['draft'], cancel=cancel)
            if not any(report['outcome'] == 'cancelled' for report in reports):
                data = deepcopy(self._data)
                _record_test(data, revision_id, _encode_reports(reports))
                self._write(data)
            return reports

    def edit(self, revision_id, example_id, inputs, expected):
        with self._lock:
            self._check_active(revision_id)
            draft = edit_example(self._revision(revision_id)['draft'], example_id, inputs, expected)
            data = deepcopy(self._data)
            new_id = self._record_revision(data, draft, 'edit_example')
            self._write(data)
            return new_id

    def correct(self, revision_id, dispatch, settings, example_id, guidance, *, requested_settings=None):
        with self._lock:
            self._check_active(revision_id)
            draft = self._revision(revision_id)['draft']
            if draft['unmet_requirements']:
                raise AuthoringError('requirements_unmet')
            metadata = _requested_metadata(settings, requested_settings)
            if type(example_id) is not str:
                raise AuthoringError('unknown_example')
            guidance = _guidance(guidance, required=True)
            return self._try_model('correct_expected', metadata, guidance, lambda: (
                correct_expected(dispatch, settings, draft, example_id, guidance), None),
                selection={'example_id': example_id})

    def improve(self, revision_id, dispatch, settings, example_ids, guidance='', *, cancel=None,
                requested_settings=None):
        with self._lock:
            self._check_active(revision_id)
            draft = self._revision(revision_id)['draft']
            metadata = _requested_metadata(settings, requested_settings)
            basis_test = _latest_test(self._data, revision_id)
            if basis_test is None:
                raise AuthoringError('select_failures')
            if type(example_ids) not in (list, tuple) or any(type(x) is not str for x in example_ids):
                raise AuthoringError('select_failures')
            example_ids = list(example_ids)
            reports = _decode_reports(basis_test['reports'])

            def propose():
                candidate, results = improve_python(
                    dispatch, settings, draft, reports, example_ids, guidance, cancel=cancel)
                if any(report['outcome'] == 'cancelled' for report in results):
                    raise AuthoringError('cancelled')
                return candidate, results

            return self._try_model('improve_python', metadata, _guidance(guidance), propose,
                                   selection={'example_ids': example_ids}, basis_test=basis_test)

    def decide(self, revision_id, attempt_id, accept, *, cancel=None):
        with self._lock:
            self._check_active(revision_id)
            attempt = self.attempt(attempt_id)
            if attempt['status'] != 'pending' or attempt['revision_id'] != revision_id:
                raise AuthoringError('stale_attempt')
            if type(accept) is not bool:
                raise AuthoringError('invalid_decision')
            data = deepcopy(self._data)
            entry = data['attempts'][attempt_id]
            if not accept:
                entry['status'] = 'rejected'
                self._write(data)
                return revision_id
            reports = entry.get('reports')
            if entry['action'] == 'correct_expected':
                results = run_examples(entry['candidate'], cancel=cancel)
                if any(report['outcome'] == 'cancelled' for report in results):
                    raise AuthoringError('cancelled')
                reports = _encode_reports(results)
            entry['status'] = 'accepted'
            new_id = self._record_revision(
                data, entry['candidate'], entry['action'], guidance=entry['guidance'],
                settings=entry['requested_settings'], attempt_id=attempt_id, reports=reports)
            entry['accepted_revision_id'] = new_id
            self._write(data)
            return new_id

    def restore(self, revision_id, selected_id):
        with self._lock:
            self._check_active(revision_id)
            selected = self._revision(selected_id)
            data = deepcopy(self._data)
            new_id = self._record_revision(data, selected['draft'], 'restore', restored_from=selected_id)
            self._write(data)
            return new_id

    def export(self, revision_id):
        with self._lock:
            revision = self._revision(revision_id)
            folder = self.directory / revision_id
            folder.mkdir(mode=0o700, exist_ok=True)
            temporary = Path(mkdtemp(prefix='.export-', dir=folder))
            destination = folder / uuid4().hex
            status = _status(_latest_reports(self._data, revision_id))
            try:
                script = temporary / 'script.py'
                script.write_bytes(revision['draft']['source'].encode('utf-8'))
                _atomic_json(temporary / 'metadata.json', dict(revision_id=revision_id, test_status=status))
                temporary.rename(destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return dict(path=str(destination / 'script.py'), test_status=status)
