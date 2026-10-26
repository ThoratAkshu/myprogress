"""Settings for `manage.py test`, which manage.py picks for that command (`--settings` still wins).

Static file names stay plain, so tests can look for "problem.js" and no collectstatic is needed first. Git
repositories and uploads go to a throwaway folder instead of the dev ones, and the real AI is never called."""
import tempfile
from pathlib import Path
from .development import *  # noqa: F401,F403

STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
# Lives as long as the test run and is removed when it ends.
_SCRATCH = tempfile.TemporaryDirectory(prefix="myprogress-tests-", ignore_cleanup_errors=True)
GIT_REPOSITORY_ROOT = Path(_SCRATCH.name) / "repositories"
MEDIA_ROOT = Path(_SCRATCH.name) / "media"
GIT_REPOSITORY_ROOT.mkdir()
MEDIA_ROOT.mkdir()
ANTHROPIC_API_KEY = ""
