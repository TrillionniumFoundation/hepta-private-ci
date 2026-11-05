"""Importable host callback whose current configuration differs from import defaults."""

MODE = 'import-default'


def predict(query):
    return MODE == 'configured-before-freeze'
