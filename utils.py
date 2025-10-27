import json
import platform
import shutil
import subprocess
import sys
import webbrowser
import zipfile
from pathlib import Path
from typing import Any, TypedDict

CJK_LANGS = ["zh", "ja", "ko"]
PROFICIENCY_VERSION = "1.0.0"
PROFICIENCY_RELEASE_URL = (
    f"https://github.com/xxyzz/Proficiency/releases/download/v{PROFICIENCY_VERSION}"
)
PROFICIENCY_MAJOR_VERSION = PROFICIENCY_VERSION.split(".", 1)[0]
WSD_LANGUAGES = {"en-en"}


class Prefs(TypedDict):
    search_people: bool
    zh_wiki_variant: str
    add_locator_map: str
    preferred_formats: list[str]
    use_all_formats: bool
    mal_x_ray_count: int
    choose_format_manually: bool
    gloss_lang: str
    use_wiktionary_for_kindle: bool
    python_path: str
    show_change_kindle_ww_lang_warning: bool
    test_wsd: bool
    torch_compute_platform: str
    custom_entity_only: bool
    use_china_proxy: bool


def load_plugin_json(plugin_path: Path, filepath: str) -> Any:
    with zipfile.ZipFile(plugin_path) as zf:
        with zipfile.Path(zf, filepath).open(encoding="utf-8") as f:
            return json.load(f)


def run_subprocess(
    args: list[str], input_str: bytes | str | None = None
) -> subprocess.CompletedProcess[bytes]:
    from calibre.gui2 import sanitize_env_vars

    with sanitize_env_vars():
        return subprocess.run(
            args,
            input=input_str,
            check=True,
            capture_output=True,
            creationflags=(
                subprocess.CREATE_NO_WINDOW  # type: ignore
                if platform.system() == "Windows"
                else 0
            ),
        )


def mac_bin_path(command: str) -> str:
    # stupid macOS loses PATH when calibre is not launched from terminal
    # search homebrew binary path first
    if platform.machine() == "arm64":
        bin_path = f"/opt/homebrew/bin/{command}"
    else:
        bin_path = f"/usr/local/bin/{command}"

    if (
        shutil.which(bin_path) is None
        and (env_bin_path := shutil.which(command)) is not None
    ):
        # assume PATH is not empty
        return env_bin_path
    return bin_path


def insert_lib_path(path: str) -> None:
    if path not in sys.path:
        sys.path.insert(0, path)


def insert_installed_libs(plugin_path: Path) -> None:
    py_v = ".".join(platform.python_version_tuple()[:2])
    insert_lib_path(str(plugin_path.parent / f"worddumb-libs-py{py_v}"))


def get_plugin_path() -> Path:
    from calibre.utils.config import config_dir

    return Path(config_dir) / "plugins/WordDumb.zip"


def custom_lemmas_folder(plugin_path: Path) -> Path:
    return plugin_path.parent / "worddumb-lemmas"


def use_kindle_ww_db(lemma_lang: str, prefs: Prefs) -> bool:
    return (
        lemma_lang == "en"
        and prefs["gloss_lang"] in ["en", "zh", "zh_cn"]
        and not prefs["use_wiktionary_for_kindle"]
    )


def kindle_db_path(plugin_path: Path, lemma_lang: str, prefs: Prefs) -> Path:
    if use_kindle_ww_db(lemma_lang, prefs):
        return (
            custom_lemmas_folder(plugin_path)
            / f"kindle_en_en_v{PROFICIENCY_MAJOR_VERSION}.db"
        )
    else:
        return wiktionary_db_path(plugin_path, lemma_lang, prefs)


def wiktionary_db_path(plugin_path: Path, lemma_lang: str, prefs: Prefs) -> Path:
    path = (
        custom_lemmas_folder(plugin_path)
        / f"wiktionary_{lemma_lang}_{prefs['gloss_lang']}_v{PROFICIENCY_MAJOR_VERSION}.db"  # noqa:E501
    )
    if is_wsd_enabled(prefs, lemma_lang):
        path = path.with_stem(path.stem + "_wsd")
    return path


def get_kindle_klld_path(plugin_path: Path, zh_gloss: bool = False) -> Path | None:
    custom_folder = custom_lemmas_folder(plugin_path)
    for path in custom_folder.glob("*.zh.klld" if zh_gloss else "*.en.klld"):
        return path
    for path in custom_folder.glob("*.zh.db" if zh_gloss else "*.en.db"):
        return path
    return None


def get_wiktionary_klld_path(plugin_path: Path, lemma_lang: str, prefs: Prefs) -> Path:
    path = (
        custom_lemmas_folder(plugin_path)
        / f"kll.{lemma_lang}.{prefs['gloss_lang']}_v{PROFICIENCY_MAJOR_VERSION}.klld"
    )
    if is_wsd_enabled(prefs, lemma_lang):
        path = path.with_stem(path.stem + "_wsd")
    return path


def donate() -> None:
    webbrowser.open("https://xxyzz.github.io/WordDumb/#donate")


def get_user_agent() -> str:
    from calibre_plugins.worddumb import VERSION

    from .error_dialogs import GITHUB_URL

    return f"WordDumb/{'.'.join(map(str, VERSION))} ({GITHUB_URL})"


def dump_prefs(prefs: Any) -> str:
    prefs_dict = prefs.defaults
    prefs_dict.update(prefs)
    return json.dumps(prefs_dict)


def spacy_model_name(lemma_lang: str, prefs: Prefs) -> str:
    languages = load_languages_data(get_plugin_path(), False)
    spacy_model = languages[lemma_lang]["spacy"]
    if spacy_model == "":
        return ""
    return spacy_model


def load_languages_data(
    plugin_path: Path, add_zh_cn: bool = True
) -> dict[str, dict[str, Any]]:
    """
    Add Simplified Chinese `zh_cn` key to languages dict for code uses `zh_cn`
    gloss language, don't add `zh_cn` for code dealing with lemma language code.
    """
    supported_languages = load_plugin_json(plugin_path, "data/languages.json")
    if add_zh_cn:
        supported_languages["zh_cn"] = supported_languages["zh"].copy()
        supported_languages["zh_cn"]["name"] = "Simplified Chinese"
    return supported_languages


def get_spacy_model_version(
    model_name: str, dependency_versions: dict[str, str]
) -> str:
    lang_code = model_name[:2]
    lang_key = f"{lang_code}_spacy_cpu_model"
    if lang_key in dependency_versions:
        return dependency_versions[lang_key]
    return dependency_versions.get("spacy_cpu_model", "")


def is_wsd_enabled(prefs: Prefs, lemma_lang: str) -> bool:
    return prefs["test_wsd"] and f"{lemma_lang}-{prefs['gloss_lang']}" in WSD_LANGUAGES


def get_book_settings_path(book_path: Path) -> Path:
    return book_path.parent / "worddumb_settings.json"
