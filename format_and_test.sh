python -m black src
python -m mypy src
python -m pylint src
python -m black src --check
python -m pytest tests