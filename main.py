from datetime import date, datetime, timedelta
from collections import Counter
from io import BytesIO
import base64
import sqlite3

from flask import Flask, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from fonctions import bdd, fermer_bdd, contexte_global, faire_slug, date_francaise, verifier_connexion

try:
    from matplotlib.figure import Figure
except ImportError:
    Figure = None

application = Flask(__name__)
application.secret_key = "cle_secrete_bibliotheque"


def txt(v):
    return str(v or "").strip()


def est_numero(valeur):
    return txt(valeur).isdigit()


def normaliser_isbn(valeur):
    brut = txt(valeur)
    chiffres = "".join(c for c in brut if c.isdigit())
    return chiffres if chiffres else brut


def email_valide(email):
    e = txt(email)
    return "@" in e and "." in e.split("@")[-1]


def code_postal_valide(cp):
    cp = txt(cp)
    return cp.isdigit() and len(cp) == 5


def date_naissance_valide(texte_date):
    d = txt(texte_date)
    try:
        return datetime.strptime(d, "%Y-%m-%d").date() <= date.today()
    except ValueError:
        return False


def reparer_ids_reservation(base, commit=False):
    # Fix qu'on a dû faire après des réservations qui ne remontaient plus dans l'historique.
    base.execute("UPDATE RESERVATION SET id_reservation = rowid WHERE id_reservation IS NULL")
    if commit:
        base.commit()


def creer_reservation(base, id_client):
    auj = date.today()
    next_id = int(base.execute("SELECT COALESCE(MAX(id_reservation),0)+1 FROM RESERVATION").fetchone()[0])
    base.execute(
        "INSERT INTO RESERVATION (id_reservation, date_reservation, date_de_retour, id_client, date_limite_retour, date_retour_effective) VALUES (?, ?, NULL, ?, ?, NULL)",
        (next_id, date_francaise(auj), id_client, date_francaise(auj + timedelta(days=21))),
    )
    return next_id


def filtrer(items, recherche, champs):
    if not recherche:
        return items
    return [x for x in items if any(recherche in str(x.get(c, "")).lower() for c in champs)]


def dispo_cd(base, cd_id):
    return base.execute(
        """
        SELECT c.id_cd_dvd, c.nom_cd_dvd,
               c.total_exemplaires - COALESCE(SUM(CASE WHEN r.date_retour_effective IS NULL THEN 1 ELSE 0 END), 0) AS exemplaires_restants
        FROM cddvd c
        LEFT JOIN ligne_cddvd lc ON lc.id_cd_dvd = c.id_cd_dvd
        LEFT JOIN RESERVATION r ON r.id_reservation = lc.id_reservation
        WHERE c.id_cd_dvd = ?
        GROUP BY c.id_cd_dvd, c.nom_cd_dvd, c.total_exemplaires
        """,
        (cd_id,),
    ).fetchone()


def stats_30j(base):
    # Version simple volontaire: on garde le format dd/mm/YYYY tel qu'il est en base.
    total = 0
    today = date.today()
    date_min = today - timedelta(days=29)
    rows = base.execute("SELECT date_reservation FROM RESERVATION WHERE date_reservation IS NOT NULL").fetchall()
    par_jour = Counter()
    for r in rows:
        raw = txt(r["date_reservation"])
        if not raw:
            continue
        try:
            jour = datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError:
            continue
        if date_min <= jour <= today:
            par_jour[jour] += 1
    data = []
    for i in range(30):
        j = date_min + timedelta(days=i)
        nb = int(par_jour.get(j, 0))
        total += nb
        data.append({"date": j.strftime("%d/%m"), "nb_reservations": nb})
    return data, total


def image_stats(data):
    if Figure is None:
        return "", "Graphique indisponible sur cet environnement (matplotlib absent)."
    try:
        fig = Figure(figsize=(8.2, 3.1))
        ax = fig.add_subplot(111)
        labels = [x["date"] for x in data]
        vals = [x["nb_reservations"] for x in data]
        x = list(range(len(labels)))
        ax.plot(x, vals, marker="o", linewidth=2, markersize=4, color="#1f77b4")
        ax.set_title("Nombre total de reservations par jour (30 derniers jours)")
        ax.set_ylabel("Nombre de reservations")
        ax.set_xticks(x[::5], [labels[i] for i in x[::5]])
        ax.grid(axis="y", alpha=0.3)
        buf = BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        return base64.b64encode(buf.getvalue()).decode("utf-8"), ""
    except Exception:
        return "", "Graphique indisponible sur cet environnement."


@application.teardown_appcontext
def nettoyage_bdd(_erreur):
    fermer_bdd(_erreur)


@application.context_processor
def injecter_contexte():
    return contexte_global()


@application.route("/favicon.ico")
def favicon():
    return send_from_directory(application.static_folder, "favicon.ico", mimetype="image/x-icon")


@application.route("/")
def accueil():
    return render_template("principal.html", nomutlisateur=session.get("utilisateur", {}).get("prenom", ""))


@application.route("/catalogue/<categorie_url>")
def catalogue(categorie_url):
    base = bdd()
    recherche = txt(request.args.get("q")).lower()
    categories = base.execute("SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie").fetchall()
    categorie = next((c for c in categories if faire_slug(c["nom_categorie"]) == categorie_url), None)
    if categorie is None:
        return redirect(url_for("accueil"))

    livres = [dict(x) for x in base.execute(
        "SELECT id_livre, nom_livre, auteur_livre, ISBN_livre, resume, image, total_exemplaires, disponibilité FROM LIVRE WHERE id_categorie=? ORDER BY nom_livre",
        (categorie["id_categorie"],),
    ).fetchall()]
    livres = filtrer(livres, recherche, ("nom_livre", "auteur_livre", "ISBN_livre"))
    for l in livres:
        l["ISBN_livre"] = str(l.get("ISBN_livre") or "")
        l["total_exemplaires"] = int(l.get("total_exemplaires") or 1)
        l["exemplaires_restants"] = int(l.get("disponibilité") or 0)
        l["disponible"] = 1 if l["exemplaires_restants"] > 0 else 0

    return render_template(
        "catalogue.html",
        categorie={"id": categorie["id_categorie"], "nom": categorie["nom_categorie"], "categorie_url": categorie_url},
        livres=livres,
        recherche=recherche,
    )


@application.route("/cddvd")
def cddvd():
    base = bdd()
    recherche = txt(request.args.get("q")).lower()
    cddvds = [dict(x) for x in base.execute(
        """
        SELECT cddvd.id_cd_dvd, cddvd.nom_cd_dvd, cddvd.annee_cd_dvd, cddvd.artiste_cd_dvd, cddvd.image, cddvd.total_exemplaires,
               cddvd.total_exemplaires - COALESCE(SUM(CASE WHEN r.date_retour_effective IS NULL THEN 1 ELSE 0 END), 0) AS exemplaires_restants
        FROM cddvd
        LEFT JOIN ligne_cddvd lc ON lc.id_cd_dvd = cddvd.id_cd_dvd
        LEFT JOIN RESERVATION r ON r.id_reservation = lc.id_reservation
        GROUP BY cddvd.id_cd_dvd, cddvd.nom_cd_dvd, cddvd.annee_cd_dvd, cddvd.artiste_cd_dvd, cddvd.image, cddvd.total_exemplaires
        ORDER BY cddvd.nom_cd_dvd
        """
    ).fetchall()]
    cddvds = filtrer(cddvds, recherche, ("nom_cd_dvd", "artiste_cd_dvd", "id_cd_dvd"))
    for c in cddvds:
        c["total_exemplaires"] = int(c.get("total_exemplaires") or 0)
        c["exemplaires_restants"] = max(0, int(c.get("exemplaires_restants") or 0))
    return render_template("cddvd.html", cddvds=cddvds, recherche=recherche)


@application.route("/reserver", methods=["GET", "POST"])
def reserver():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    # Sécurité: on répare les IDs avant de joindre sur les vues historique/compte.
    reparer_ids_reservation(base, commit=True)
    id_client = session["utilisateur"]["id"]
    message = None
    erreur = None

    if request.method == "POST":
        isbn = txt(request.form.get("isbn"))
        numero = txt(request.form.get("numero_cd_dvd"))
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numero CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numero CD/DVD."
        elif isbn:
            # On tolère ISBN avec tirets/espaces pour éviter de bloquer l'utilisateur.
            isbn_norm = normaliser_isbn(isbn)
            livre = base.execute(
                "SELECT id_livre, nom_livre, disponibilité FROM LIVRE WHERE CAST(ISBN_livre AS TEXT)=? OR CAST(ISBN_livre AS TEXT)=? ORDER BY id_livre LIMIT 1",
                (isbn, isbn_norm),
            ).fetchone()
            if not livre:
                erreur = "Livre introuvable pour cet ISBN."
            elif int(livre["disponibilité"] or 0) <= 0:
                erreur = "Ce livre est actuellement indisponible."
            else:
                resa_id = creer_reservation(base, id_client)
                base.execute("INSERT INTO ligne_livre (id_livre, id_reservation) VALUES (?, ?)", (livre["id_livre"], resa_id))
                base.execute("UPDATE LIVRE SET disponibilité = disponibilité - 1 WHERE id_livre = ?", (livre["id_livre"],))
                base.commit()
                message = "Reservation enregistree pour le livre : " + str(livre["nom_livre"])
        else:
            if not est_numero(numero):
                erreur = "Le numero CD/DVD doit etre un nombre."
                historique = base.execute(
                    "SELECT type_media, id_reservation, nom_media, reference_media, date_reservation, date_limite_retour, date_retour_effective FROM VUE_HISTORIQUE_RESERVATIONS WHERE id_client=? ORDER BY id_reservation DESC",
                    (id_client,),
                ).fetchall()
                return render_template("reserver.html", message=message, erreur=erreur, historique=historique)
            cd = dispo_cd(base, numero)
            if not cd:
                erreur = "CD/DVD introuvable pour ce numero."
            elif int(cd["exemplaires_restants"] or 0) <= 0:
                erreur = "Ce CD/DVD est actuellement indisponible."
            else:
                resa_id = creer_reservation(base, id_client)
                base.execute("INSERT INTO ligne_cddvd (id_cd_dvd, id_reservation, date_de_retour) VALUES (?, ?, NULL)", (cd["id_cd_dvd"], resa_id))
                base.commit()
                message = "Reservation enregistree pour le CD/DVD : " + str(cd["nom_cd_dvd"])

    historique = base.execute(
        "SELECT type_media, id_reservation, nom_media, reference_media, date_reservation, date_limite_retour, date_retour_effective FROM VUE_HISTORIQUE_RESERVATIONS WHERE id_client=? ORDER BY id_reservation DESC",
        (id_client,),
    ).fetchall()
    return render_template("reserver.html", message=message, erreur=erreur, historique=historique)


@application.route("/mes_reservations")
def mes_reservations():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    reparer_ids_reservation(base, commit=True)
    reservations = base.execute(
        "SELECT type_media, id_reservation, nom_media, auteur_media, reference_media, date_reservation, date_limite_retour, date_retour_effective FROM VUE_MES_RESERVATIONS WHERE id_client=? ORDER BY id_reservation DESC",
        (session["utilisateur"]["id"],),
    ).fetchall()
    return render_template("mes_reservations.html", reservations=reservations)


@application.route("/rendre", methods=["GET", "POST"])
def rendre():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    reparer_ids_reservation(base, commit=True)
    id_client = session["utilisateur"]["id"]
    message = None
    erreur = None

    if request.method == "POST":
        isbn = txt(request.form.get("isbn"))
        numero = txt(request.form.get("numero_cd_dvd"))
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numero CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numero CD/DVD."
        elif isbn:
            isbn_norm = normaliser_isbn(isbn)
            resa = base.execute(
                "SELECT r.id_reservation, l.id_livre, l.nom_livre FROM RESERVATION r JOIN ligne_livre ll ON ll.id_reservation=r.id_reservation JOIN LIVRE l ON l.id_livre=ll.id_livre WHERE r.id_client=? AND (CAST(l.ISBN_livre AS TEXT)=? OR CAST(l.ISBN_livre AS TEXT)=?) AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1",
                (id_client, isbn, isbn_norm),
            ).fetchone()
            if not resa:
                erreur = "Aucune reservation active pour cet ISBN."
            else:
                auj = date_francaise(date.today())
                base.execute("UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?", (auj, auj, resa["id_reservation"]))
                base.execute("UPDATE LIVRE SET disponibilité = disponibilité + 1 WHERE id_livre=?", (resa["id_livre"],))
                base.commit()
                message = "Retour enregistre pour le livre : " + str(resa["nom_livre"])
        else:
            if not est_numero(numero):
                erreur = "Le numero CD/DVD doit etre un nombre."
                return render_template("rendre.html", message=message, erreur=erreur)
            resa = base.execute(
                "SELECT r.id_reservation, cddvd.id_cd_dvd, cddvd.nom_cd_dvd FROM RESERVATION r JOIN ligne_cddvd ON ligne_cddvd.id_reservation = r.id_reservation JOIN cddvd ON cddvd.id_cd_dvd = ligne_cddvd.id_cd_dvd WHERE r.id_client=? AND ligne_cddvd.id_cd_dvd=? AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1",
                (id_client, numero),
            ).fetchone()
            if not resa:
                erreur = "Aucune reservation pour ce numero CD/DVD."
            else:
                auj = date_francaise(date.today())
                base.execute("UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?", (auj, auj, resa["id_reservation"]))
                base.execute("UPDATE ligne_cddvd SET date_de_retour=? WHERE id_reservation=?", (auj, resa["id_reservation"]))
                base.commit()
                message = "Retour enregistre pour le CD/DVD : " + str(resa["nom_cd_dvd"])

    return render_template("rendre.html", message=message, erreur=erreur)


@application.route("/connexion", methods=["GET", "POST"])
def connexion():
    base = bdd()
    erreur = None
    prochain = request.values.get("next") or url_for("accueil")
    if request.method == "POST":
        identifiant = txt(request.form.get("email")).lower()
        mot_de_passe = request.form.get("password", "")
        utilisateur = base.execute(
            "SELECT * FROM CLIENT WHERE (LOWER(adressemail_client)=? OR LOWER(COALESCE(nom_utilisateur,''))=?) AND mot_de_passe IS NOT NULL LIMIT 1",
            (identifiant, identifiant),
        ).fetchone()
        if not utilisateur:
            erreur = "Adresse e-mail ou nom d'utilisateur introuvable."
        elif not check_password_hash(utilisateur["mot_de_passe"], mot_de_passe):
            erreur = "Mot de passe incorrect."
        else:
            session["utilisateur"] = {
                "id": utilisateur["id_client"],
                "prenom": utilisateur["prenom_client"],
                "nom_utilisateur": utilisateur["nom_utilisateur"],
                "email": utilisateur["adressemail_client"],
            }
            if utilisateur["est_admin"] == 1:
                session["admin"] = True
                return redirect(url_for("admin"))
            session.pop("admin", None)
            return redirect(prochain)
    return render_template("connexion.html", erreur=erreur, prochain=prochain)


@application.route("/creer_compte", methods=["POST"])
def creer_compte():
    base = bdd()
    prochain = request.form.get("next") or url_for("accueil")
    prenom = txt(request.form.get("prenom"))
    nom_utilisateur = txt(request.form.get("nom_utilisateur"))
    date_naissance = txt(request.form.get("date_naissance"))
    code_postal = txt(request.form.get("code_postal"))
    email = txt(request.form.get("email")).lower()
    mot_de_passe = request.form.get("password", "")

    if not all([prenom, nom_utilisateur, date_naissance, code_postal, email, mot_de_passe]):
        return render_template("connexion.html", erreur="Tous les champs sont obligatoires.", prochain=prochain)
    if len(prenom) < 2 or len(nom_utilisateur) < 3:
        return render_template("connexion.html", erreur="Prenom ou nom d'utilisateur trop court.", prochain=prochain)
    if len(mot_de_passe) < 6:
        return render_template("connexion.html", erreur="Mot de passe trop court (6 caracteres minimum).", prochain=prochain)
    if not email_valide(email):
        return render_template("connexion.html", erreur="Adresse e-mail invalide.", prochain=prochain)
    if not code_postal_valide(code_postal):
        return render_template("connexion.html", erreur="Code postal invalide (5 chiffres).", prochain=prochain)
    if not date_naissance_valide(date_naissance):
        return render_template("connexion.html", erreur="Date de naissance invalide.", prochain=prochain)

    deja = base.execute(
        "SELECT 1 FROM CLIENT WHERE LOWER(adressemail_client)=? OR LOWER(COALESCE(nom_utilisateur,''))=? LIMIT 1",
        (email, nom_utilisateur.lower()),
    ).fetchone()
    if deja:
        return render_template("connexion.html", erreur="Cet e-mail ou ce nom d'utilisateur existe deja.", prochain=prochain)

    try:
        mdp_hash = generate_password_hash(mot_de_passe)
        cur = base.execute(
            "INSERT INTO CLIENT (nom_client, prenom_client, adressepostale_client, adressemail_client, date_naissance_client, telephone_client, nom_utilisateur, mot_de_passe, date_creation, code_postal, est_admin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (nom_utilisateur, prenom, code_postal, email, date_naissance, None, nom_utilisateur, mdp_hash, date_francaise(date.today()), code_postal),
        )
        base.commit()
    except sqlite3.IntegrityError:
        return render_template("connexion.html", erreur="Cet e-mail ou ce nom d'utilisateur existe deja.", prochain=prochain)

    session["utilisateur"] = {"id": cur.lastrowid, "prenom": prenom, "nom_utilisateur": nom_utilisateur, "email": email}
    session.pop("admin", None)
    return redirect(prochain)


@application.route("/autres")
@application.route("/statistiques")
def autres():
    base = bdd()
    nb_clients = int(base.execute("SELECT COUNT(*) FROM CLIENT").fetchone()[0])
    nb_reservations_actives = int(base.execute("SELECT COUNT(*) FROM RESERVATION WHERE date_retour_effective IS NULL").fetchone()[0])
    top_livres_demandes = [dict(x) for x in base.execute(
        "SELECT l.id_livre, l.nom_livre, c.nom_categorie, COUNT(*) AS nb_demandes FROM LIGNE_LIVRE ll JOIN LIVRE l ON l.id_livre = ll.id_livre LEFT JOIN CATEGORIE c ON c.id_categorie = l.id_categorie GROUP BY l.id_livre, l.nom_livre, c.nom_categorie ORDER BY nb_demandes DESC, l.nom_livre ASC LIMIT 10"
    ).fetchall()]
    for l in top_livres_demandes:
        l["slug_categorie"] = faire_slug(l.get("nom_categorie") or "")
    data, total_30j = stats_30j(base)
    img, err = image_stats(data)
    return render_template(
        "autres.html",
        nb_clients=nb_clients,
        nb_reservations_actives=nb_reservations_actives,
        total_reservations_30j=total_30j,
        stats_chart_image=img,
        stats_chart_error=err,
        top_livres_demandes=top_livres_demandes,
    )


@application.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("connexion", next=url_for("admin")))
    base = bdd()
    message = None
    erreur = None
    categories = [dict(x) for x in base.execute("SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY nom_categorie").fetchall()]

    if request.method == "POST":
        # TODO (plus tard): découper ce bloc en sous-fonctions ajouter/supprimer pour alléger la route.
        action = txt(request.form.get("action"))
        isbn = txt(request.form.get("isbn_livre"))
        if not isbn:
            erreur = "L'ISBN est obligatoire."
        elif action == "ajouter":
            nom = txt(request.form.get("nom_livre"))
            auteur = txt(request.form.get("auteur_livre"))
            resume = txt(request.form.get("resume_livre"))
            id_categorie = txt(request.form.get("id_categorie"))
            existe = base.execute("SELECT nom_livre FROM LIVRE WHERE ISBN_livre=? LIMIT 1", (isbn,)).fetchone()
            if existe:
                base.execute("UPDATE LIVRE SET total_exemplaires = COALESCE(total_exemplaires, 0) + 1, disponibilité = COALESCE(disponibilité, 0) + 1 WHERE ISBN_livre=?", (isbn,))
                base.commit()
                message = f"Exemplaire ajoute pour '{existe['nom_livre']}' (ISBN {isbn})."
            elif not nom:
                erreur = "Le nom du livre est obligatoire pour un nouveau livre."
            elif not id_categorie:
                erreur = "Veuillez choisir une categorie pour un nouveau livre."
            elif not est_numero(id_categorie):
                erreur = "Categorie invalide."
            else:
                base.execute(
                    "INSERT INTO LIVRE (nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires, disponibilité) VALUES (?, ?, NULL, NULL, ?, ?, ?, NULL, 1, 1)",
                    (nom, auteur or "Inconnu", int(id_categorie), isbn, resume or None),
                )
                base.commit()
                message = f"Le livre '{nom}' a ete ajoute avec succes."
        elif action == "supprimer":
            livre = base.execute("SELECT nom_livre FROM LIVRE WHERE ISBN_livre=? LIMIT 1", (isbn,)).fetchone()
            if not livre:
                erreur = "Aucun livre trouve pour cet ISBN."
            else:
                base.execute("DELETE FROM LIVRE WHERE ISBN_livre=?", (isbn,))
                base.commit()
                message = f"Le livre '{livre['nom_livre']}' a ete definitivement retire."
        else:
            erreur = "Action inconnue."

    livres = [dict(x) for x in base.execute("SELECT nom_livre, ISBN_livre FROM LIVRE ORDER BY id_livre DESC LIMIT 30").fetchall()]
    for livre in livres:
        livre["ISBN_livre"] = str(livre.get("ISBN_livre") or "")
    return render_template("admin.html", livres=livres, categories=categories, erreur=erreur, message=message)


@application.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


if __name__ == "__main__":
    application.run(debug=True)
