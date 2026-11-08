"""Repository-only release checks; installed-wheel checks live in the consumer suite."""
import importlib.util
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (ROOT / 'scripts/build_release.py').is_file(),
                                reason='release tooling is intentionally absent from wheel')


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'scripts/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changed_since_tracks_shipped_files_only(builder, tmp_path, monkeypatch):
    if shutil.which('git') is None:
        pytest.skip('git unavailable')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)

    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    git('init', '-q')
    git('config', 'user.name', 'Release test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'README.md').write_text('original')
    git('add', '.')
    git('commit', '-qm', 'baseline')
    git('tag', 'v0.1.0')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/check.py').write_text('# tooling only')
    git('add', '.')
    git('commit', '-qm', 'tooling')
    assert not builder.changed_since('v0.1.0')
    (tmp_path / 'README.md').write_text('changed metadata')
    git('add', '.')
    git('commit', '-qm', 'payload')
    assert builder.changed_since('v0.1.0')


def test_release_version_and_news_are_required(builder, tmp_path):
    (tmp_path / 'scriptspell').mkdir()
    version_path = tmp_path / 'scriptspell/_version.py'
    version_path.write_text('__version__ = "0.1.1"\n')
    assert builder.read_version(tmp_path) == '0.1.1'
    (tmp_path / 'NEWS.md').write_text('## 0.1.0\n')
    with pytest.raises(SystemExit, match='NEWS.md'):
        builder.check_news(tmp_path, '0.1.1')
    version_path.write_text('__version__ = "invalid"\n')
    with pytest.raises(SystemExit, match='_version.py'):
        builder.read_version(tmp_path)


def test_export_head_extracts_the_committed_tree(builder, tmp_path):
    if shutil.which('git') is None:
        pytest.skip('git unavailable')
    builder.export_head(tmp_path)
    assert (tmp_path / 'src/pyproject.toml').is_file()
    assert (tmp_path / 'src/scriptspell/_version.py').is_file()


def write_tar(path, members):
    """Write one member per (name, kind) pair; kind is 'dir', 'link' or file content."""
    with tarfile.open(path, 'w') as tar:
        for name, kind in members:
            info = tarfile.TarInfo(name)
            if kind == 'dir':
                info.type = tarfile.DIRTYPE
                # git archive records 0755 directories; without the execute bit the
                # extracted tree cannot be traversed and the test would fail spuriously.
                info.mode = 0o755
                tar.addfile(info)
            elif kind == 'link':
                info.type = tarfile.SYMTYPE
                info.linkname = '/etc/passwd'
                tar.addfile(info)
            else:
                data = kind.encode()
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))


def test_extraction_without_data_filter_still_extracts_safe_members(builder, tmp_path, monkeypatch):
    # The macOS runner resolves the supported 3.10 range to 3.10.11, which has no filter.
    monkeypatch.setattr(builder, '_data_filter_available', lambda: False)
    archive = tmp_path / 'safe.tar'
    write_tar(archive, [('pkg/', 'dir'), ('pkg/module.py', 'x = 1')])
    builder._extract(archive, tmp_path / 'out')
    assert (tmp_path / 'out/pkg/module.py').read_text() == 'x = 1'


@pytest.mark.parametrize('name,kind', [('../escape.txt', 'x = 1'),
                                       ('/absolute.txt', 'x = 1'),
                                       ('link', 'link')])
def test_extraction_without_data_filter_refuses_unsafe_members(builder, tmp_path, monkeypatch, name, kind):
    monkeypatch.setattr(builder, '_data_filter_available', lambda: False)
    archive = tmp_path / 'unsafe.tar'
    write_tar(archive, [(name, kind)])
    with pytest.raises(SystemExit, match='refusing archive member'):
        builder._extract(archive, tmp_path / 'out/inner')
    assert not (tmp_path / 'escape.txt').exists()
    assert not (tmp_path / 'absolute.txt').exists()
    assert not (tmp_path / 'out/inner/link').exists()
