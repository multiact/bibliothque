import sqlite3


BASE_DONNEES = "bibliotheque.db"


def bdd(path=BASE_DONNEES):
    connexion = sqlite3.connect(path)
    connexion.row_factory = sqlite3.Row
    return connexion
