import logging
from pathlib import Path

import cookies_store
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

_IG_PATH = ("extractor", "instagram")
_TW_PATH = ("extractor", "twitter")


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
                # Twitter
                "category", "user", "content", "tweet_id", "date",
                # Instagram (older/most fields)
                "uploader", "uploader_id",
                # Instagram (newer API fields)
                "username", "fullname", "owner_id", "description",
                # Common
                "post_url",
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
    bucket = cookies_store.bucket_for_host(url)
    ext_path = _IG_PATH if bucket == "instagram" else _TW_PATH if bucket == "twitter" else None
    if ext_path is not None:
        gd_config.set(ext_path, "user-agent", _DEFAULT_UA)
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
