import platform
import shutil
import tarfile
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, build_opener, getproxies

from calibre.constants import isfrozen, islinux, ismacos, iswindows

from .utils import (
    PROFICIENCY_RELEASE_URL,
    Prefs,
    custom_lemmas_folder,
    get_plugin_path,
    get_spacy_model_version,
    get_user_agent,
    load_plugin_json,
    mac_bin_path,
    run_subprocess,
)

PY_PATH = ""
LIBS_PATH = Path()
CHINA_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
# https://pytorch.org/get-started/locally
PYTORCH_LINUX_PLATFORMS = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cuda12.6": "https://download.pytorch.org/whl/cu126",
    "cuda12.8": None,
    "cuda13.0": "https://download.pytorch.org/whl/cu130",
    "rocm6.4": "https://download.pytorch.org/whl/rocm6.4",
}
PYTORCH_WINDOWS_PLATFORMS = {
    "cpu": None,
    "cuda12.6": "https://download.pytorch.org/whl/cu126",
    "cuda12.8": "https://download.pytorch.org/whl/cu128",
    "cuda13.0": "https://download.pytorch.org/whl/cu130",
}
# macOS uses standard PyPI for both Intel and Apple Silicon
PYTORCH_MACOS_PLATFORMS = {
    "cpu": None,  # Standard PyPI, works for both Intel and Apple Silicon
    "mps": None,  # Metal Performance Shaders for Apple Silicon GPU acceleration
}


def install_deps(pkg: str, notif: Any) -> None:
    global PY_PATH, LIBS_PATH
    plugin_path = get_plugin_path()

    if len(PY_PATH) == 0:
        PY_PATH, py_version = which_python()
        LIBS_PATH = plugin_path.parent.joinpath(f"worddumb-libs-py{py_version}")
        if not LIBS_PATH.is_dir():
            for old_libs_path in LIBS_PATH.parent.glob("worddumb-libs-py*"):
                shutil.rmtree(old_libs_path)

    from .config import prefs

    china_index = CHINA_PYPI_MIRROR if prefs["use_china_proxy"] else None
    dep_versions = load_plugin_json(plugin_path, "data/deps.json")
    if pkg == "lxml":
        pip_install("lxml", dep_versions["lxml"], notif=notif, index_url=china_index)
    elif pkg == "wsd":
        pip_install(
            "transformers",
            dep_versions["transformers"],
            notif=notif,
            index_url=china_index,
        )
        if prefs["torch_compute_platform"] != "cpu":
            pip_install(
                "accelerate",
                dep_versions["accelerate"],
                notif=notif,
                index_url=china_index,
            )
        pytorch_extra_index = None
        if iswindows:
            pytorch_extra_index = PYTORCH_WINDOWS_PLATFORMS.get(
                prefs["torch_compute_platform"]
            )
        elif islinux:
            pytorch_extra_index = PYTORCH_LINUX_PLATFORMS.get(
                prefs["torch_compute_platform"]
            )
        elif ismacos:
            pytorch_extra_index = PYTORCH_MACOS_PLATFORMS.get(
                prefs["torch_compute_platform"]
            )
        pip_install(
            "torch",
            dep_versions["torch"],
            extra_index=pytorch_extra_index,
            notif=notif,
            index_url=china_index,
        )
    else:
        # Install X-Ray dependencies
        pip_install(
            "rapidfuzz", dep_versions["rapidfuzz"], notif=notif, index_url=china_index
        )
        pip_install("spacy", dep_versions["spacy"], notif=notif, index_url=china_index)
        if pkg != "":
            model_version = get_spacy_model_version(pkg, dep_versions)
            url = (
                "https://github.com/explosion/spacy-models/releases/download/"
                f"{pkg}-{model_version}/{pkg}-{model_version}-py3-none-any.whl"
            )
            pip_install(pkg, model_version, url=url, notif=notif, index_url=china_index)


def which_python() -> tuple[str, str]:
    """
    Return Python command or file path and version string
    """
    from .config import prefs

    py = "python3"
    if len(prefs["python_path"]) > 0:
        py = prefs["python_path"]
    elif iswindows:
        py = "py"
    elif ismacos:
        py = mac_bin_path("python3")

    if shutil.which(py) is None:
        raise Exception("PythonNotFound")

    if isfrozen or prefs["python_path"] != "":
        r = run_subprocess(
            [
                py,
                "-c",
                'import platform; print(".".join(platform.python_version_tuple()[:2]))',
            ]
        )
        py_v = r.stdout.decode().strip()
    else:
        py_v = ".".join(platform.python_version_tuple()[:2])
    py_v_tuple = tuple(map(int, py_v.split(".")))
    if py_v_tuple < (3, 11):
        # https://github.com/kovidgoyal/calibre/blob/master/bypy/sources.json
        raise Exception("OutdatedPython")
    elif py_v_tuple > (3, 13):  # spaCy
        raise Exception("UnsupportedPython")
    return py, py_v


def pip_install(
    pkg: str,
    pkg_version: str,
    url: str | None = None,
    extra_index: str | None = None,
    no_deps: bool = False,
    notif: Any = None,
    index_url: str | None = None,
) -> None:
    pattern = f"{pkg.replace('-', '_')}-{pkg_version}*"
    if pkg == "torch" and extra_index:
        pattern = f"torch-{pkg_version}+{extra_index.split('/')[-1]}*"
    if not any(LIBS_PATH.glob(pattern)):
        if notif:
            notif.put((0, f"Installing {pkg}"))

        args = [
            PY_PATH,
            "-m",
            "pip",
            "--disable-pip-version-check",
            "install",
            "-U",
            "-t",
            str(LIBS_PATH),
            "--no-user",  # disable "--user" option which conflicts with "-t"
            "--no-cache-dir",
        ]

        if no_deps:
            args.append("--no-deps")

        if url:
            args.append(url)
        elif pkg_version:
            args.append(f"{pkg}=={pkg_version}")
        else:
            args.append(pkg)

        if index_url is not None:
            args.extend(["--index-url", index_url])
        if extra_index is not None:
            args.extend(["--extra-index-url", extra_index])

        run_subprocess(args)


def download_word_wise_file(
    is_kindle: bool,
    lemma_lang: str,
    prefs: Prefs,
    abort=None,
    log=None,
    notifications=None,
) -> None:
    from .utils import is_wsd_enabled

    gloss_lang = prefs["gloss_lang"]
    if notifications:
        notifications.put(
            (
                0,
                f"Downloading {lemma_lang}-{gloss_lang} "
                f"{'Kindle' if is_kindle else 'Wiktionary'} file",
            )
        )
    plugin_path = get_plugin_path()
    bz2_filename = f"{lemma_lang}_{gloss_lang}.tar.bz2"
    url = f"{PROFICIENCY_RELEASE_URL}/{bz2_filename}"
    download_folder = custom_lemmas_folder(plugin_path)
    if not download_folder.is_dir():
        download_folder.mkdir()
    checksum = download_checksum(False)
    download_path = download_folder / bz2_filename
    download_extract_bz2(url, download_path, checksum.get(bz2_filename, ""))
    if is_wsd_enabled(prefs, lemma_lang):
        bz2_filename = f"{lemma_lang}_{gloss_lang}_wsd.tar.bz2"
        url = f"{PROFICIENCY_RELEASE_URL}/{bz2_filename}"
        download_path = download_folder / bz2_filename
        checksum = download_checksum(True)
        download_extract_bz2(url, download_path, checksum.get(bz2_filename, ""))


def download_extract_bz2(url: str, download_path: Path, sha256: str) -> None:
    download_file(url, download_path, sha256)
    with tarfile.open(name=download_path, mode="r:bz2") as tar_f:
        tar_f.extractall(download_path.parent)
    download_path.unlink()


def download_checksum(is_wsd: bool) -> dict[str, str]:
    import json

    if not is_wsd:
        url = f"{PROFICIENCY_RELEASE_URL}/sha256.json"
    else:
        url = f"{PROFICIENCY_RELEASE_URL}/sha256_wsd.json"
    opener = build_opener(ProxyHandler(getproxies()))
    opener.addheaders = [("User-agent", get_user_agent())]
    with opener.open(url) as r:
        return json.load(r)


def download_file(
    url: str, download_path: Path, sha256: str, range: int = 0, retry: int = 10
):
    import hashlib

    opener = build_opener(ProxyHandler(getproxies()))
    headers = [("User-agent", get_user_agent())]
    if range > 0:
        headers.append(("Range", f"bytes={range}-"))
    opener.addheaders = headers
    saved_bytes = 0
    content_length = 0
    with opener.open(url) as r, open(download_path, "wb" if range == 0 else "ab") as f:
        shutil.copyfileobj(r, f)
        saved_bytes = f.tell()
        content_length = int(r.headers.get("content-length"))

    if saved_bytes < content_length + range:
        if retry == 1:
            download_path.unlink()
            raise Exception("DownloadFailed")
        else:
            download_file(url, download_path, sha256, saved_bytes, retry - 1)
    else:
        with download_path.open("rb", buffering=0) as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != sha256:
                download_path.unlink()
                if retry == 1:
                    raise Exception("DownloadFailed")
                else:
                    download_file(url, download_path, sha256, retry=retry - 1)
