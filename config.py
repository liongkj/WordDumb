import json
import webbrowser
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from calibre.constants import isfrozen, islinux, ismacos, iswindows
from calibre.gui2 import Dispatcher
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre.utils.config import JSONConfig
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtSql import QSqlDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .custom_lemmas import CustomLemmasDialog
from .deps import download_word_wise_file, install_deps, which_python
from .dump_lemmas import dump_spacy_docs
from .error_dialogs import GITHUB_URL, change_kindle_ww_lang_dialog, job_failed
from .import_lemmas import apply_imported_lemmas_data, export_lemmas_job
from .utils import (
    custom_lemmas_folder,
    donate,
    dump_prefs,
    get_plugin_path,
    kindle_db_path,
    load_languages_data,
    run_subprocess,
    spacy_model_name,
    wiktionary_db_path,
)

prefs = JSONConfig("plugins/worddumb")
prefs.defaults["search_people"] = False
prefs.defaults["zh_wiki_variant"] = "cn"
prefs.defaults["add_locator_map"] = False
prefs.defaults["preferred_formats"] = ["KFX", "AZW3", "AZW", "MOBI", "EPUB"]
prefs.defaults["use_all_formats"] = False
prefs.defaults["minimal_x_ray_count"] = 1
prefs.defaults["choose_format_manually"] = True
prefs.defaults["gloss_lang"] = "en"
prefs.defaults["use_wiktionary_for_kindle"] = False
prefs.defaults["python_path"] = ""
prefs.defaults["show_change_kindle_ww_lang_warning"] = True
prefs.defaults["test_wsd"] = True
prefs.defaults["torch_compute_platform"] = "cpu"
prefs.defaults["custom_entity_only"] = False
prefs.defaults["use_china_proxy"] = False
for code in load_languages_data(get_plugin_path(), False).keys():
    prefs.defaults[f"{code}_wiktionary_difficulty_limit"] = 5

load_translations()  # type: ignore
if TYPE_CHECKING:
    _: Any


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.plugin_path = get_plugin_path()

        vl = QVBoxLayout()
        self.setLayout(vl)

        format_order_button = QPushButton(_("Preferred format order"), self)
        format_order_button.clicked.connect(self.open_format_order_dialog)
        vl.addWidget(format_order_button)

        customize_ww_button = QPushButton(_("Customize Kindle Word Wise"))
        customize_ww_button.clicked.connect(
            partial(self.open_choose_lemma_lang_dialog, is_kindle=True)
        )
        vl.addWidget(customize_ww_button)

        custom_wiktionary_button = QPushButton(_("Customize EPUB Wiktionary"))
        custom_wiktionary_button.clicked.connect(
            partial(self.open_choose_lemma_lang_dialog, is_kindle=False)
        )
        vl.addWidget(custom_wiktionary_button)

        self.search_people_box = QCheckBox(
            _(
                "Fetch X-Ray people descriptions from Wikipedia or other "
                "MediaWiki server"
            )
        )
        self.search_people_box.setToolTip(
            _(
                "Enable this option for nonfiction books and novels that have character"
                " pages on Wikipedia or other MediaWiki server"
            )
        )
        self.search_people_box.setChecked(prefs["search_people"])
        vl.addWidget(self.search_people_box)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        python_path_label = QLabel(_("Python path"))
        python_path_label.setToolTip(
            _(
                "Absolute path of the executable binary for the Python interpreter, "
                "leave this empty to find Python in PATH."
            )
        )
        self.python_path = QLineEdit()
        self.python_path.setText(prefs["python_path"])
        form_layout.addRow(python_path_label, self.python_path)

        self.minimal_x_ray_count = QSpinBox()
        self.minimal_x_ray_count.setMinimum(1)
        self.minimal_x_ray_count.setValue(prefs["minimal_x_ray_count"])
        minimal_x_ray_label = QLabel(_("Minimal X-Ray occurrences"))
        minimal_x_ray_label.setToolTip(
            _(
                "X-Ray entities that appear less then this number and don't have "
                "description from Wikipedia or other MediaWiki server will be removed"
            )
        )
        form_layout.addRow(minimal_x_ray_label, self.minimal_x_ray_count)

        self.zh_wiki_box = QComboBox()
        zh_variants = {
            "cn": "大陆简体",
            "hk": "香港繁體",
            "mo": "澳門繁體",
            "my": "大马简体",
            "sg": "新加坡简体",
            "tw": "臺灣正體",
        }
        for variant, text in zh_variants.items():
            self.zh_wiki_box.addItem(text, variant)
        self.zh_wiki_box.setCurrentText(zh_variants[prefs["zh_wiki_variant"]])
        form_layout.addRow(_("Chinese Wikipedia variant"), self.zh_wiki_box)

        if islinux or iswindows or ismacos:
            compute_platform_lb = QLabel(_("PyTorch compute platform"))
            if ismacos:
                compute_platforms = {
                    "cpu": "CPU",
                    "mps": "MPS (Apple Silicon GPU)",
                }
            else:
                compute_platforms = {
                    "cpu": "CPU",
                    "cuda13.0": "CUDA 13.0",
                    "cuda12.8": "CUDA 12.8",
                    "cuda12.6": "CUDA 12.6",
                    "rocm6.4": "ROCm 6.4",
                }
            self.compute_platform_box = QComboBox()
            for version, text in compute_platforms.items():
                if iswindows and text.startswith("ROCm"):
                    continue
                self.compute_platform_box.addItem(text, version)
            if prefs["torch_compute_platform"] not in compute_platforms:
                prefs["torch_compute_platform"] = "cpu"
            self.compute_platform_box.setCurrentText(
                compute_platforms[prefs["torch_compute_platform"]]
            )
            form_layout.addRow(compute_platform_lb, self.compute_platform_box)

        vl.addLayout(form_layout)

        self.locator_map_box = QCheckBox(_("Add locator map to EPUB footnotes"))
        self.locator_map_box.setToolTip(
            _("Enable this option if your e-reader supports image in footnotes")
        )
        self.locator_map_box.setChecked(prefs["add_locator_map"])
        vl.addWidget(self.locator_map_box)

        self.custom_entity_only = QCheckBox(_("Only use customized X-Ray entities"))
        self.custom_entity_only.setChecked(prefs["custom_entity_only"])
        vl.addWidget(self.custom_entity_only)

        self.use_china_proxy_box = QCheckBox(_("Use China PyPI mirror (Tsinghua)"))
        self.use_china_proxy_box.setToolTip(
            _("Use https://pypi.tuna.tsinghua.edu.cn/simple for pip installations")
        )
        self.use_china_proxy_box.setChecked(prefs["use_china_proxy"])
        vl.addWidget(self.use_china_proxy_box)

        delete_file_button = QPushButton(_("Delete downloaded files"))
        delete_file_button.clicked.connect(self.open_delete_files_dialog)
        vl.addWidget(delete_file_button)

        donate_button = QPushButton(QIcon.ic("donate.png"), _("Donate"))
        donate_button.clicked.connect(donate)
        vl.addWidget(donate_button)

        doc_button = QPushButton(_("Document"))
        doc_button.clicked.connect(self.open_document)
        vl.addWidget(doc_button)

        github_button = QPushButton(_("Source code"))
        github_button.clicked.connect(self.open_github)
        vl.addWidget(github_button)

    def open_document(self) -> None:
        webbrowser.open("https://xxyzz.github.io/WordDumb")

    def open_github(self) -> None:
        webbrowser.open(GITHUB_URL)

    def save_settings(self) -> None:
        prefs["python_path"] = self.python_path.text()
        prefs["search_people"] = self.search_people_box.isChecked()
        prefs["zh_wiki_variant"] = self.zh_wiki_box.currentData()
        prefs["add_locator_map"] = self.locator_map_box.isChecked()
        prefs["minimal_x_ray_count"] = self.minimal_x_ray_count.value()
        prefs["custom_entity_only"] = self.custom_entity_only.isChecked()
        prefs["use_china_proxy"] = self.use_china_proxy_box.isChecked()
        if islinux or iswindows or ismacos:
            prefs["torch_compute_platform"] = self.compute_platform_box.currentData()

    def open_format_order_dialog(self):
        format_order_dialog = FormatOrderDialog(self)
        if format_order_dialog.exec():
            format_order_dialog.save()

    def open_choose_lemma_lang_dialog(self, is_kindle: bool = True) -> None:
        choose_lang_dlg = ChooseLemmaLangDialog(self, is_kindle)
        if choose_lang_dlg.exec():
            lemma_lang = choose_lang_dlg.lemma_lang_box.currentData()
            gloss_lang = choose_lang_dlg.gloss_lang_box.currentData()
            prefs["gloss_lang"] = gloss_lang
            if is_kindle and lemma_lang == "en" and gloss_lang in ["en", "zh", "zh_cn"]:
                prefs["use_wiktionary_for_kindle"] = (
                    choose_lang_dlg.use_wiktionary_box.isChecked()
                )

            db_path = (
                kindle_db_path(self.plugin_path, lemma_lang, prefs)
                if is_kindle
                else wiktionary_db_path(self.plugin_path, lemma_lang, prefs)
            )
            if not db_path.exists():
                self.run_threaded_job(
                    download_word_wise_file,
                    (is_kindle, lemma_lang, prefs),
                    _("Downloading Word Wise file"),
                )
            else:
                custom_lemmas_dlg = CustomLemmasDialog(
                    self, is_kindle, lemma_lang, gloss_lang, db_path
                )
                if custom_lemmas_dlg.exec():
                    QSqlDatabase.removeDatabase(custom_lemmas_dlg.db_connection_name)
                    self.run_threaded_job(
                        dump_lemmas_job,
                        (is_kindle, db_path, lemma_lang),
                        _("Saving customized lemmas"),
                    )
                elif hasattr(custom_lemmas_dlg, "import_lemmas_path"):
                    QSqlDatabase.removeDatabase(custom_lemmas_dlg.db_connection_name)
                    self.run_threaded_job(
                        import_lemmas_job,
                        (
                            Path(custom_lemmas_dlg.import_lemmas_path),
                            db_path,
                            custom_lemmas_dlg.retain_enabled_lemmas,
                            is_kindle,
                            lemma_lang,
                        ),
                        _("Saving customized lemmas"),
                    )
                elif hasattr(custom_lemmas_dlg, "export_path"):
                    QSqlDatabase.removeDatabase(custom_lemmas_dlg.db_connection_name)
                    self.run_threaded_job(
                        export_lemmas_job,
                        (
                            db_path,
                            Path(custom_lemmas_dlg.export_path),
                            custom_lemmas_dlg.only_export_enabled,
                            custom_lemmas_dlg.export_difficulty_limit,
                            is_kindle,
                            lemma_lang,
                            gloss_lang,
                        ),
                        _("Exporting customized lemmas"),
                    )
                else:
                    QSqlDatabase.removeDatabase(custom_lemmas_dlg.db_connection_name)

    def run_threaded_job(self, func, args, job_title):
        gui = self.parent()
        while gui.parent() is not None:
            gui = gui.parent()
        job = ThreadedJob(
            "WordDumb's dumb job",
            job_title,
            func,
            args,
            {},
            Dispatcher(partial(job_failed, parent=gui)),
            killable=False,
        )
        gui.job_manager.run_threaded_job(job)

    def open_delete_files_dialog(self):
        dialog = DeleteFilesDialog(self)
        if dialog.exec():
            paths = []
            plugin_path = get_plugin_path()
            if dialog.delete_dependencies.isChecked():
                paths.extend(list(plugin_path.parent.glob("worddumb-libs-py*")))
            if dialog.delete_definitions.isChecked():
                paths.append(custom_lemmas_folder(plugin_path))
            if dialog.delete_mediawiki.isChecked():
                paths.append(plugin_path.parent / "worddumb-mediawiki")
                paths.append(plugin_path.parent / "worddumb-wikimedia")
            if len(paths) > 0:
                self.run_threaded_job(delete_files, (paths,), _("Deleting files"))


def import_lemmas_job(
    import_path: Path,
    db_path: Path,
    retain_lemmas: bool,
    is_kindle: bool,
    lemma_lang: str,
    abort: Any = None,
    log: Any = None,
    notifications: Any = None,
) -> None:
    apply_imported_lemmas_data(db_path, import_path, retain_lemmas, lemma_lang)
    dump_lemmas_job(is_kindle, db_path, lemma_lang)


def dump_lemmas_job(
    is_kindle: bool,
    db_path: Path,
    lemma_lang: str,
    abort: Any = None,
    log: Any = None,
    notifications: Any = None,
) -> None:
    plugin_path = get_plugin_path()
    model_name = spacy_model_name(lemma_lang, prefs)
    install_deps(model_name, notifications)
    if isfrozen:
        options = {
            "is_kindle": is_kindle,
            "db_path": str(db_path),
            "lemma_lang": lemma_lang,
            "plugin_path": str(plugin_path),
            "model_name": model_name,
        }
        args = [
            which_python()[0],
            str(plugin_path),
            json.dumps(options),
            dump_prefs(prefs),
        ]
        run_subprocess(args)
    else:
        dump_spacy_docs(model_name, is_kindle, lemma_lang, db_path, plugin_path, prefs)


class FormatOrderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Preferred format order"))
        vl = QVBoxLayout()
        self.setLayout(vl)

        self.format_list = QListWidget()
        self.format_list.setAlternatingRowColors(True)
        self.format_list.setDragEnabled(True)
        self.format_list.viewport().setAcceptDrops(True)
        self.format_list.setDropIndicatorShown(True)
        self.format_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.format_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.format_list.addItems(prefs["preferred_formats"])
        vl.addWidget(self.format_list)

        self.choose_format_manually = QCheckBox(_("Choose format manually"))
        self.choose_format_manually.setChecked(prefs["choose_format_manually"])
        self.choose_format_manually.stateChanged.connect(
            self.disable_all_formats_button
        )
        vl.addWidget(self.choose_format_manually)

        self.use_all_formats = QCheckBox(_("Create files for all available formats"))
        self.use_all_formats.setChecked(prefs["use_all_formats"])
        self.disable_all_formats_button(self.choose_format_manually.checkState().value)
        vl.addWidget(self.use_all_formats)

        save_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button_box.accepted.connect(self.accept)
        save_button_box.rejected.connect(self.reject)
        vl.addWidget(save_button_box)

    def save(self):
        prefs["preferred_formats"] = [
            self.format_list.item(index).text()
            for index in range(self.format_list.count())
        ]
        prefs["choose_format_manually"] = self.choose_format_manually.isChecked()
        prefs["use_all_formats"] = self.use_all_formats.isChecked()

    def disable_all_formats_button(self, choose_format_state: int) -> None:
        if choose_format_state == Qt.CheckState.Checked.value:
            self.use_all_formats.setChecked(False)
            self.use_all_formats.setDisabled(True)
        else:
            self.use_all_formats.setEnabled(True)


class ChooseFormatDialog(QDialog):
    def __init__(self, formats: list[str]) -> None:
        super().__init__()
        self.setWindowTitle(_("Choose book format"))
        vl = QVBoxLayout()
        self.setLayout(vl)

        message = QLabel(
            _(
                "This book has multiple supported formats. Choose the format "
                "you want to use."
            )
        )
        vl.addWidget(message)

        self.choose_format_manually = QCheckBox(
            _("Always ask when more than one format is available")
        )
        self.choose_format_manually.setChecked(True)
        vl.addWidget(self.choose_format_manually)

        format_buttons = QDialogButtonBox()
        for book_format in formats:
            button = format_buttons.addButton(
                book_format, QDialogButtonBox.ButtonRole.AcceptRole
            )
            button.clicked.connect(partial(self.accept_format, button.text()))
        vl.addWidget(format_buttons)

    def accept_format(self, chosen_format: str) -> None:
        self.chosen_format = chosen_format
        if not self.choose_format_manually.isChecked():
            prefs["choose_format_manually"] = False
        self.accept()


class ChooseLemmaLangDialog(QDialog):
    def __init__(self, parent: QObject, is_kindle: bool):
        super().__init__(parent)
        self.setWindowTitle(_("Choose language"))
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.lemma_lang_box = QComboBox()
        self.gloss_lang_box = QComboBox()
        language_dict = load_languages_data(get_plugin_path())
        selected_gloss_code = prefs["gloss_lang"]
        self.gloss_lang_box.currentIndexChanged.connect(
            partial(self.gloss_lang_changed, language_dict)
        )
        for gloss_lang, lang_value in language_dict.items():
            if lang_value.get("gloss_source", []) == "":
                continue
            gloss_lang_name = _(lang_value["name"])
            self.gloss_lang_box.addItem(gloss_lang_name, gloss_lang)
            if gloss_lang == selected_gloss_code:
                self.gloss_lang_box.setCurrentText(gloss_lang_name)
        self.gloss_lang_changed(language_dict)
        form_layout.addRow(_("Definition language"), self.gloss_lang_box)
        form_layout.addRow(_("Book language"), self.lemma_lang_box)

        if is_kindle:
            self.use_wiktionary_box = QCheckBox("")
            self.kindle_lang_changed(True)
            self.lemma_lang_box.currentIndexChanged.connect(self.kindle_lang_changed)
            self.gloss_lang_box.currentIndexChanged.connect(self.kindle_lang_changed)
            self.use_wiktionary_box.toggled.connect(
                partial(change_kindle_ww_lang_dialog, parent=self, prefs=prefs)
            )
            form_layout.addRow(_("Use Wiktionary definition"), self.use_wiktionary_box)

        confirm_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        confirm_button_box.accepted.connect(self.accept)
        confirm_button_box.rejected.connect(self.reject)

        vl = QVBoxLayout()
        vl.addLayout(form_layout)
        vl.addWidget(confirm_button_box)
        self.setLayout(vl)

    def kindle_lang_changed(self, first_call: bool = False) -> None:
        if (
            self.lemma_lang_box.currentData() == "en"
            and self.gloss_lang_box.currentData() in ["en", "zh", "zh_cn"]
        ):
            self.use_wiktionary_box.setEnabled(True)
            self.use_wiktionary_box.setChecked(prefs["use_wiktionary_for_kindle"])
        else:
            self.use_wiktionary_box.setChecked(True)
            self.use_wiktionary_box.setDisabled(True)
            if not first_call:
                change_kindle_ww_lang_dialog(True, self, prefs)

    def gloss_lang_changed(self, lang_dict) -> None:
        gloss_lang = self.gloss_lang_box.currentData()
        self.lemma_lang_box.clear()
        lemma_langs = lang_dict[gloss_lang].get("lemma_languages", [])
        if len(lemma_langs) == 0:
            lemma_langs = lang_dict.keys()
        for index, lemma_lang in enumerate(lemma_langs):
            if lemma_lang == "zh_cn":
                continue
            lemma_lang_name = _(lang_dict[lemma_lang]["name"])
            self.lemma_lang_box.addItem(lemma_lang_name, lemma_lang)
            if index == 0:
                self.lemma_lang_box.setCurrentText(lemma_lang_name)


class DeleteFilesDialog(QDialog):
    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.setWindowTitle(_("Delete downloaded files"))
        vl = QVBoxLayout()
        self.setLayout(vl)

        self.delete_dependencies = QCheckBox(_("Delete dependency packages"))
        vl.addWidget(self.delete_dependencies)
        self.delete_definitions = QCheckBox(_("Delete definition files"))
        vl.addWidget(self.delete_definitions)
        self.delete_mediawiki = QCheckBox(_("Delete MediaWiki files"))
        vl.addWidget(self.delete_mediawiki)

        confirm_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        confirm_button_box.accepted.connect(self.accept)
        confirm_button_box.rejected.connect(self.reject)
        vl.addWidget(confirm_button_box)


def delete_files(
    paths: list[Path],
    abort: Any = None,
    log: Any = None,
    notifications: Any = None,
):
    import shutil

    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)


class BookSettingsDialog(QDialog):
    def __init__(self, parent: QObject, config_path: Path):
        super().__init__(parent)
        self.setWindowTitle(_("Book settings"))
        vl = QVBoxLayout()
        self.setLayout(vl)
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        vl.addLayout(form_layout)
        self.config_path = config_path
        self.settings = {}
        if self.config_path.is_file():
            with self.config_path.open() as f:
                self.settings = json.load(f)

        self.mediawiki_api = QLineEdit()
        self.mediawiki_api.setText(self.settings.get("mediawiki_api", ""))
        self.mediawiki_api.setPlaceholderText("https://wiki.domain/w/api.php")
        mediawiki_api_lb = QLabel(_("MediaWiki Action API"))
        mediawiki_api_lb.setToolTip(_("Level this empty to use Wikipedia API"))
        form_layout.addRow(mediawiki_api_lb, self.mediawiki_api)

        confirm_button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        confirm_button_box.accepted.connect(self.accept)
        confirm_button_box.rejected.connect(self.reject)
        vl.addWidget(confirm_button_box)
        vl.addWidget(confirm_button_box)

    def save(self):
        mediawiki_api = self.mediawiki_api.text().strip("/ ")
        if (
            mediawiki_api.startswith(("https://", "http://"))
            and mediawiki_api.endswith("/api.php")
        ) or mediawiki_api == "":
            self.settings["mediawiki_api"] = mediawiki_api
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2)
