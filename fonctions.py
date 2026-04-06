import sqlite3
from flask import g, redirect, request, session, url_for


BASE_DONNEES = "bibliotheque.db"


def bdd(base_path=BASE_DONNEES):
    if "bdd" not in g:
        g.bdd = sqlite3.connect(base_path)
        g.bdd.row_factory = sqlite3.Row
    return g.bdd


def fermer_bdd(_erreur=None):
    connexion = g.pop("bdd", None)
    if connexion:
        connexion.close()


def date_francaise(valeur_date):
    return valeur_date.strftime("%d/%m/%Y")


def faire_slug(texte):
    return "-".join(str(texte).strip().lower().split()) # permet de convertir un m eSSage en message


def prochain_identifiant(base, table, colonne):
    sql = (
        'SELECT COALESCE(MAX(CAST("' + colonne + '" AS INTEGER)), 0) + 1 AS prochain '
        + 'FROM "' + table + '"'
    )
    return int(base.execute(sql).fetchone()["prochain"])


def categories_menu(base_path=BASE_DONNEES):
    try:
        lignes = bdd(base_path).execute(
            "SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie"
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": l["id_categorie"],
            "nom": l["nom_categorie"],
            "categorie_url": faire_slug(l["nom_categorie"]),
        }
        for l in lignes
    ]


def verifier_connexion():
    if "utilisateur" not in session:
        return redirect(url_for("connexion", next=request.path))
    return None


def contexte_global(base_path=BASE_DONNEES):
    return {
        "utilisateur": session.get("utilisateur"),
        "admin_connecte": bool(session.get("admin")),
        "menu_categories": categories_menu(base_path),
    }


def charger_historique_reservations(base, utilisateur_id):
    return base.execute(
        """
        SELECT type_media, id_reservation, nom_media, reference_media, date_reservation, date_limite_retour, date_retour_effective
        FROM VUE_HISTORIQUE_RESERVATIONS
        WHERE id_client = ?
        ORDER BY id_reservation DESC
        """,
        (utilisateur_id,),
    ).fetchall()


def charger_mes_reservations(base, utilisateur_id):
    return base.execute(
        """
        SELECT type_media, id_reservation, nom_media, auteur_media, reference_media, date_reservation, date_limite_retour, date_retour_effective
        FROM VUE_MES_RESERVATIONS
        WHERE id_client = ?
        ORDER BY id_reservation DESC
        """,
        (utilisateur_id,),
    ).fetchall()
