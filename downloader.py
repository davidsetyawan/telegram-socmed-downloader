import logging
from pathlib import Path
from urllib.parse import urlparse

from gallery_dl import config as gd_config
from gallery_dl import exception as gdlex
from gallery_dl import job as gd_job

_log = logging.getLogger(__name__)


class DownloadError(Exception):
    pass


# A modern Chrome user-agent helps when IG/Twitter reject the default
# python-requests UA during fingerprint checks. Override per-extractor
# so the value applies only to IG/Twitter, not other extractors.
_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_IG_HOSTS = ("instagram.com",)
_TW_HOSTS = ("twitter.com", "x.com")


def _extractor_path_for(url: str) -> tuple[str, ...] | None:
    host = (urlparse(url).hostname or "").lower()
    if any(h in host for h in _IG_HOSTS):
        return ("extractor", "instagram")
    if any(h in host for h in _TW_HOSTS):
        return ("extractor", "twitter")
    return None


def run(url: str, out_dir: Path, cookies_path: Path | None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gd_config.load(("--",))
    if cookies_path is not None:
        gd_config.set(("extractor",), "cookies", str(cookies_path))
    gd_config.set((), "base-directory", str(out_dir))
    ext_path = _extractor_path_for(url)
    if ext_path is not None:
        gd_config.set(ext_path, "user-agent", _DEFAULT_UA)
    try:
        j = gd_job.DownloadJob(url)
        j.run()
    except (gdlex.AuthenticationError, gdlex.AuthorizationError) as e:
        raise DownloadError("cookies invalid / login required") from e
    except gdlex.NoExtractorError as e:
        raise DownloadError("URL not recognized by gallery-dl (not Instagram/Twitter?)") from e
    except Exception as e:
        _log.error("gallery-dl failure for %s: %s", url, traceback.format_exc())
        raise DownloadError(f"download failed: {type(e).__name__}: {e}") from e

    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    if not files and ext_path is not None:
        # Common reason: IG redirected to home (cookies rejected / profile
        # not authorized for the logged-in user). gallery-dl already logs
        # the underlying cause; we add a hint for the operator.
        _log.info(
            "0 files for %s — likely cookies stale, profile private, or "
            "the cookies' account is not authorized to view this profile",
            url,
        )
    return files
