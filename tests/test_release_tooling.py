"""Repository-only release checks; installed-wheel checks live in the consumer suite."""
import importlib.util
import shutil
import subprocess
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
