import sqlite3
from flask import Flask
def bdd():
    # Une connexion SQLite par requête Flask, stockée dans `g` pour réutilisation locale.
    if "bdd" not in g:
        g.bdd = sqlite3.connect(BASE_DONNEES)
        g.bdd.row_factory = sqlite3.Row
    return g.bdd
def fermer_bdd(_erreur):
    connexion = g.pop("bdd", None)
    if connexion:
        connexion.close()