import logging
from pathlib import Path
from urllib.parse import urlparse

from gallery_dl import config as gd_config
from gallery_dl import exception as gdlex
from gallery_dl import job as gd_job

_log = logging.getLogger(__name__)


class DownloadError(Exception):
    pass


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


class _KwdictCollectingJob(gd_job.DownloadJob):
    """Subclass that captures every kwdict gallery-dl produces.

    gallery-dl emits `(image_num, url, kwdict)` 3-tuples from the
    extractor's `__iter__` and turns them into file writes. We hook by
    overriding `handle_url` so the kwdict is appended to a shared list
    before the file is processed. The list is then returned alongside
    the downloaded file paths.
    """

    def __init__(self, url, kwdict_list, cfg=None):
        super().__init__(url, cfg)
        self._kwdict_list = kwdict_list

    def handle_url(self, url, kwdict):
        # Capture a shallow copy of the kwdict before the parent writes
        # the file. We only keep the fields we'll need for the caption.
        captured = {
            k: kwdict.get(k)
            for k in (
                "category", "uploader", "uploader_id",
                "post_url", "content", "tweet_id", "date", "user",
            )
        }
        self._kwdict_list.append(captured)
        return super().handle_url(url, kwdict)


def run(url: str, out_dir: Path, cookies_path: Path | None) -> tuple[list[Path], list[dict]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gd_config.load(("--",))
    if cookies_path is not None:
        gd_config.set(("extractor",), "cookies", str(cookies_path))
    gd_config.set((), "base-directory", str(out_dir))
    ext_path = _extractor_path_for(url)
    if ext_path is not None:
        gd_config.set(ext_path, "user-agent", _DEFAULT_UA)
    kwdicts: list[dict] = []
    try:
        j = _KwdictCollectingJob(url, kwdicts)
        j.run()
    except (gdlex.AuthenticationError, gdlex.AuthorizationError) as e:
        raise DownloadError("cookies invalid / login required") from e
    except gdlex.NoExtractorError as e:
        raise DownloadError("URL not recognized by gallery-dl (not Instagram/Twitter?)") from e
    except Exception as e:
        _log.error("gallery-dl failure for %s: %s", url, __import__("traceback").format_exc())
        raise DownloadError(f"download failed: {type(e).__name__}: {e}") from e

    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    if not files and ext_path is not None:
        _log.info(
            "0 files for %s — likely cookies stale, profile private, or "
            "the cookies' account is not authorized to view this profile",
            url,
        )
    # Trim captured kwdicts to match file count (gallery-dl can emit a
    # kwdict for a media that fails to download).
    kwdicts = kwdicts[: len(files)]
    return files, kwdicts
