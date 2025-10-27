# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WordDumb is a Calibre plugin that generates Kindle Word Wise and X-Ray files and EPUB footnotes, then sends them to e-readers. It supports KFX, AZW3, AZW, MOBI, and EPUB formats.

## Development Commands

### Building the Plugin

**Unix (Linux/macOS):**
```bash
zip -r worddumb.zip * -x@exclude.lst
```

**Windows:**
```bash
7z a -x@exclude.lst -x!.* -tzip worddumb.zip
```

### Installing the Plugin
```bash
calibre-customize -a worddumb.zip
```

### Running Tests
```bash
cd tests && calibre-debug test.py
```

Set these environment variables when running tests:
- `PYTHONOPTIMIZE=1`
- `PYTHONWARNINGS=default`
- `CALIBRE_SHOW_DEPRECATION_WARNINGS=1`

### Linting

**Type checking:**
```bash
python -m mypy .
python -m mypy __main__.py
```

**Code formatting and linting:**
```bash
python -m ruff check .
python -m ruff format --diff .
```

**Spell checking:**
```bash
typos
```

### CLI Usage

The plugin can be run from the command line:
```bash
calibre-debug -r WordDumb -- [options] book_path [book_path ...]
```

Options:
- `-w`: Create Word Wise only
- `-x`: Create X-Ray only
- `-v, --version`: Show version
- If neither `-w` nor `-x` is specified, both are created

### Compiling Translations
```bash
calibre-debug -c "from calibre.translations.msgfmt import main; main()" translations/*.po
```

## Architecture

### Core Components

1. **Plugin Entry Points:**
   - `__init__.py`: Main plugin class `WordDumbDumb` that integrates with Calibre
   - `ui.py`: GUI interface with `WordDumb` class extending `InterfaceAction`
   - `__main__.py`: CLI interface for command-line usage

2. **Job Processing Pipeline:**
   - `parse_job.py`: Contains `ParseJobData` dataclass and `do_job()` function - the core processing engine
   - `metadata.py`: Handles book metadata extraction and validation
   - Jobs run in background threads via Calibre's `ThreadedJob` system

3. **Word Wise Generation:**
   - `database.py`: Creates SQLite databases for Word Wise (Language Layer `.kll` files)
   - `import_lemmas.py`: Imports lemma data from various sources
   - `dump_lemmas.py`: Processes spaCy linguistic data
   - `custom_lemmas.py`: Handles user-defined custom lemmas
   - `wsd.py`: Word Sense Disambiguation using BERT multilingual model

4. **X-Ray Generation:**
   - `x_ray.py`: Main X-Ray class that creates X-Ray databases
   - `x_ray_share.py`: Shared X-Ray utilities and data structures
   - `custom_x_ray.py`: Dialog for customizing X-Ray entities
   - Uses Named Entity Recognition (NER) with spaCy to identify characters, places, etc.
   - Fetches entity descriptions from Wikipedia/Wikidata via `mediawiki.py`

5. **Book Format Handling:**
   - `epub.py`: EPUB-specific processing
   - Supports KFX, AZW3, AZW, MOBI through Calibre's format APIs

6. **External Dependencies:**
   - `deps.py`: Manages installation of Python packages (spaCy models, PyTorch, transformers, etc.)
   - Packages installed to `worddumb-libs-py{version}` directory
   - Supports various PyTorch compute platforms:
     - **Linux**: CPU, CUDA 12.6/12.8/13.0, ROCm 6.4
     - **Windows**: CPU, CUDA 12.6/12.8/13.0
     - **macOS**: CPU, MPS (Metal Performance Shaders for Apple Silicon GPU acceleration)

7. **Supporting Modules:**
   - `config.py`: Plugin configuration and preferences
   - `send_file.py`: Sends generated files to connected e-readers
   - `mediawiki.py`: Wikipedia and Wikidata API integration
   - `interval.py`: Interval tree data structure for text position tracking
   - `utils.py`: Common utilities and constants
   - `error_dialogs.py`: Error handling UI

### Data Flow

1. User selects book(s) in Calibre GUI or provides path via CLI
2. `check_metadata()` validates book format, language, and extracts metadata
3. `ParseJobData` dataclass created with book info and preferences
4. `do_job()` orchestrates the processing:
   - Installs required dependencies if missing (spaCy models, PyTorch, etc.)
   - Parses book content
   - For Word Wise: runs spaCy NLP pipeline, performs WSD if enabled, creates `.kll` database
   - For X-Ray: runs NER, queries Wikipedia/Wikidata, creates X-Ray database
5. Generated files saved alongside the book file
6. Optionally sends files to connected device

### Key Design Patterns

- **Dual import paths**: All modules use try/except to support both plugin context (with `calibre_plugins` prefix) and standalone execution
- **In-memory SQLite**: Databases created in memory, then saved to disk to avoid partial writes
- **Job-based architecture**: Long-running tasks execute in background threads with progress notifications
- **Subprocess isolation**: spaCy and ML models run in separate Python subprocess to avoid conflicts with Calibre's embedded Python
- **Caching**: Wikipedia data cached to `worddumb-wikimedia` directory; spaCy docs cached per book

### Configuration

- Plugin preferences stored via Calibre's config system
- Per-book settings stored in JSON files at `{book_dir}/.worddumb/{book_name}.json`
- Custom X-Ray entity data stored at `{book_dir}/.worddumb/{book_name}_x.json`

### Language Support

- Word Wise: Languages defined in `data/languages.json` with support matrix for different gloss languages
- X-Ray: Limited to languages with Wikipedia coverage and spaCy NER models
- CJK (Chinese, Japanese, Korean) languages have special handling

## Important Notes

- The plugin modifies book files by adding sidecar databases, but never modifies the original book content
- Requires Calibre 7.1.0 or later
- ML features (WSD) require PyTorch and transformers - heavyweight dependencies installed on-demand
- Testing requires test books and KFX Input plugin to be installed

## Platform-Specific Notes

### macOS / Apple Silicon
- PyTorch on macOS (both Intel and Apple Silicon) is installed from standard PyPI (no extra index URL needed)
- Apple Silicon users can select "MPS (Apple Silicon GPU)" in preferences for GPU acceleration using Metal Performance Shaders
- The torch package automatically detects the architecture and installs appropriate binaries
- numpy is automatically installed as a dependency of torch - if you see numpy errors, it typically indicates torch didn't install correctly
