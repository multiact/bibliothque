from flask import Flask, render_template, request, redirect, url_for, session, g
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "cle_secrete_bibliotheque"

nom_base = "bibliotheque.db"

def avoir_base():
    if "base" not in g:
        g.base = sqlite3.connect(nom_base)
        g.base.row_factory = sqlite3.Row
    return g.base

@app.teardown_appcontext
def fermer_base(erreur):
    base = g.pop("base", None)
    if base is not None:
        base.close()

def creer_tables():
    base = avoir_base()

    base.execute("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prenom TEXT NOT NULL,
            nom_utilisateur TEXT NOT NULL UNIQUE,
            date_naissance TEXT NOT NULL,
            code_postal TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            mot_de_passe TEXT NOT NULL
        )
    """)

    base.execute("""
        CREATE TABLE IF NOT EXISTS livres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            auteur TEXT NOT NULL,
            isbn TEXT NOT NULL UNIQUE,
            categorie TEXT NOT NULL,
            resume TEXT NOT NULL,
            image TEXT NOT NULL,
            disponible INTEGER NOT NULL DEFAULT 1
        )
    """)

    base.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_utilisateur INTEGER NOT NULL,
            id_livre INTEGER NOT NULL,
            date_reservation TEXT,
            bibliotheque TEXT,
            rendue INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(id_utilisateur) REFERENCES utilisateurs(id),
            FOREIGN KEY(id_livre) REFERENCES livres(id)
        )
    """)

    base.commit()

@app.before_request
def avant_chaque_page():
    creer_tables()

@app.context_processor
def envoyer_utilisateur():
    return dict(utilisateur=session.get("utilisateur"))

@app.route("/")
def accueil():
    return render_template("principal.html")

@app.route("/catalogue/<categorie>")
def catalogue(categorie):
    base = avoir_base()
    livres = base.execute(
        "SELECT * FROM livres WHERE categorie = ? ORDER BY titre",
        (categorie,)
    ).fetchall()
    return render_template("catalogue.html", categorie=categorie, livres=livres)

@app.route("/cddvd")
def cddvd():
    return render_template("cddvd.html")

@app.route("/reserver", methods=["GET", "POST"])
def reserver():
    if "utilisateur" not in session:
        return redirect(url_for("connexion"))

    message = None
    erreur = None
    base = avoir_base()

    if request.method == "POST":
        isbn = request.form["isbn"]
        bibliotheque = request.form["bibliotheque"]
        date_reservation = request.form["date_reservation"]

        livre = base.execute(
            "SELECT * FROM livres WHERE isbn = ?",
            (isbn,)
        ).fetchone()

        if livre is None:
            erreur = "Aucun livre trouvé avec cet ISBN."
        elif livre["categorie"] == "cddvd":
            erreur = "Cette page ne gère pas les CD / DVD."
        elif livre["disponible"] == 0:
            erreur = "Ce livre est déjà réservé."
        else:
            base.execute(
                """
                INSERT INTO reservations (id_utilisateur, id_livre, date_reservation, bibliotheque, rendue)
                VALUES (?, ?, ?, ?, 0)
                """,
                (session["utilisateur"]["id"], livre["id"], date_reservation, bibliotheque)
            )
            base.execute(
                "UPDATE livres SET disponible = 0 WHERE id = ?",
                (livre["id"],)
            )
            base.commit()
            message = "Réservation enregistrée."

    return render_template("reserver.html", message=message, erreur=erreur)

@app.route("/mes_reservations")
def mes_reservations():
    if "utilisateur" not in session:
        return redirect(url_for("connexion"))

    base = avoir_base()
    reservations = base.execute(
        """
        SELECT reservations.id, livres.titre, livres.auteur, livres.isbn, reservations.date_reservation, reservations.bibliotheque, reservations.rendue
        FROM reservations
        JOIN livres ON reservations.id_livre = livres.id
        WHERE reservations.id_utilisateur = ?
        ORDER BY reservations.id DESC
        """,
        (session["utilisateur"]["id"],)
    ).fetchall()

    return render_template("mes_reservations.html", reservations=reservations)

@app.route("/rendre", methods=["GET", "POST"])
def rendre():
    if "utilisateur" not in session:
        return redirect(url_for("connexion"))

    message = None
    erreur = None
    base = avoir_base()

    if request.method == "POST":
        isbn = request.form["isbn"]

        reservation = base.execute(
            """
            SELECT reservations.id AS id_reservation, livres.id AS id_livre, livres.titre
            FROM reservations
            JOIN livres ON reservations.id_livre = livres.id
            WHERE reservations.id_utilisateur = ?
              AND livres.isbn = ?
              AND reservations.rendue = 0
            ORDER BY reservations.id DESC
            LIMIT 1
            """,
            (session["utilisateur"]["id"], isbn)
        ).fetchone()

        if reservation is None:
            erreur = "Aucune réservation en cours trouvée avec cet ISBN."
        else:
            base.execute(
                "UPDATE reservations SET rendue = 1 WHERE id = ?",
                (reservation["id_reservation"],)
            )
            base.execute(
                "UPDATE livres SET disponible = 1 WHERE id = ?",
                (reservation["id_livre"],)
            )
            base.commit()
            message = f"Retour enregistré pour : {reservation['titre']}"

    return render_template("rendre.html", message=message, erreur=erreur)

@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    erreur = None

    if request.method == "POST":
        email = request.form["email"]
        mot_de_passe = request.form["password"]

        base = avoir_base()
        utilisateur = base.execute(
            "SELECT * FROM utilisateurs WHERE email = ?",
            (email,)
        ).fetchone()

        if utilisateur is None:
            erreur = "Adresse mail introuvable."
        elif not check_password_hash(utilisateur["mot_de_passe"], mot_de_passe):
            erreur = "Mot de passe incorrect."
        else:
            session["utilisateur"] = {
                "id": utilisateur["id"],
                "prenom": utilisateur["prenom"],
                "nom_utilisateur": utilisateur["nom_utilisateur"],
                "email": utilisateur["email"]
            }
            return redirect(url_for("accueil"))

    return render_template("connexion.html", erreur=erreur)

@app.route("/creer_compte", methods=["GET", "POST"])
def creer_compte():
    erreur = None

    if request.method == "POST":
        prenom = request.form["prenom"]
        nom_utilisateur = request.form["nom_utilisateur"]
        date_naissance = request.form["date_naissance"]
        code_postal = request.form["code_postal"]
        email = request.form["email"]
        mot_de_passe = request.form["password"]

        base = avoir_base()

        deja_existant = base.execute(
            "SELECT * FROM utilisateurs WHERE email = ? OR nom_utilisateur = ?",
            (email, nom_utilisateur)
        ).fetchone()

        if deja_existant is not None:
            erreur = "Cet email ou ce nom d'utilisateur existe déjà."
        else:
            mot_de_passe_cache = generate_password_hash(mot_de_passe)
            base.execute(
                """
                INSERT INTO utilisateurs (prenom, nom_utilisateur, date_naissance, code_postal, email, mot_de_passe)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prenom, nom_utilisateur, date_naissance, code_postal, email, mot_de_passe_cache)
            )
            base.commit()
            return redirect(url_for("connexion"))

    return render_template("connexion.html", erreur=erreur)

@app.route("/deconnexion")
def deconnexion():
    session.pop("utilisateur", None)
    return redirect(url_for("accueil"))

if __name__ == "__main__":
    app.run(debug=True)
