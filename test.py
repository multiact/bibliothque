from datetime import date, datetime, timedelta
from io import BytesIO
import base64
import json
import os
import sqlite3
import unicodedata
from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
application = Flask(__name__)
application.secret_key = "cle_secrete_bibliotheque"
application.jinja_env.variable_start_string = "[["
application.jinja_env.variable_end_string = "]]"
application.jinja_env.block_start_string = "[%"
application.jinja_env.block_end_string = "%]"
BASE_DONNEES = "bibliotheque.db"
DOSSIER_COUVERTURES = os.path.join("static", "couvertures")
def bdd():
    if "bdd" not in g:
        g.bdd = sqlite3.connect(BASE_DONNEES)
        g.bdd.row_factory = sqlite3.Row
    return g.bdd
@application.teardown_appcontext
def fermer_bdd(_erreur):
    connexion = g.pop("bdd", None)
    if connexion:
        connexion.close()
def date_francaise(valeur_date):
    return valeur_date.strftime("%d/%m/%Y")
def prefixe_categorie_image(nom_categorie):
    nom = unicodedata.normalize("NFKD", str(nom_categorie)).encode("ascii", "ignore").decode("ascii").lower().strip()
    correspondances = {
        "roman classique": "roman",
        "science fiction": "sciencefiction",
        "developpement personnel": "devperso",
    }
    if nom in correspondances:
        return correspondances[nom]
    return "".join(nom.split()) if nom else "livre"
def prochain_nom_image_livre(base, id_categorie):
    categorie = base.execute(
        "SELECT nom_categorie FROM CATEGORIE WHERE id_categorie = ?",
        (id_categorie,),
    ).fetchone()
    if not categorie:
        return "livre_01.jpg"
    prefixe = prefixe_categorie_image(categorie["nom_categorie"])
    total = base.execute(
        "SELECT COUNT(*) AS total FROM LIVRE WHERE id_categorie = ?",
        (id_categorie,),
    ).fetchone()["total"]
    return "%s_%02d.jpg" % (prefixe, int(total) + 1)
def prochain_nom_image_cddvd(base):
    total = base.execute('SELECT COUNT(*) AS total FROM "CD/DVD"').fetchone()["total"]
    return "cddvd_%02d.jpg" % (int(total) + 1)
def enregistrer_image_upload(fichier, nom_fichier):
    if not fichier or not fichier.filename:
        return None
    os.makedirs(DOSSIER_COUVERTURES, exist_ok=True)
    nom_securise = secure_filename(nom_fichier or fichier.filename)
    if not nom_securise:
        return None
    chemin_destination = os.path.join(DOSSIER_COUVERTURES, nom_securise)
    fichier.save(chemin_destination)
    return "couvertures/" + nom_securise
def faire_slug(texte):
    texte_ascii = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode("ascii")
    return "-".join(texte_ascii.lower().strip().split())
def categories_menu():
    base = bdd()
    lignes = base.execute("SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie").fetchall()
    return [{"id": ligne["id_categorie"], "nom": ligne["nom_categorie"], "slug": faire_slug(ligne["nom_categorie"])} for ligne in lignes]
def prochain_identifiant(base, table, colonne):
    return int(
        base.execute(
            'SELECT COALESCE(MAX(CAST("' + colonne + '" AS INTEGER)), 0) + 1 AS prochain FROM "' + table + '"'
        ).fetchone()["prochain"]
    )
def ajouter_log_connexion(id_client):
    base = bdd()
    base.execute(
        "INSERT INTO CONNEXION_LOG (id_client, date_connexion) VALUES (?, ?)",
        (id_client, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    base.commit()
def verifier_connexion():
    if "utilisateur" not in session:
        return redirect(url_for("connexion", next=request.path))
    return None
@application.context_processor
def contexte_global():
    return {
        "utilisateur": session.get("utilisateur"),
        "menu_categories": categories_menu(),
    }
@application.route("/")
def accueil():
    return render_template("principal.html")
@application.route("/catalogue/<slug>")
def catalogue(slug):
    base = bdd()
    recherche = request.args.get("q", "").strip().lower()
    categorie = next((element for element in categories_menu() if element["slug"] == slug), None)
    if not categorie:
        return redirect(url_for("accueil"))
    parametres = [categorie["id"]]
    filtre = ""
    if recherche:
        filtre = " AND (LOWER(nom_livre) LIKE ? OR LOWER(auteur_livre) LIKE ? OR isbn_livre LIKE ?)"
        motif = "%" + recherche + "%"
        parametres = [categorie["id"], motif, motif, motif]
    livres = base.execute(
        """
        SELECT
            id_livre,
            nom_livre,
            auteur_livre,
            isbn_livre AS ISBN_livre,
            resume,
            image,
            total_exemplaires,
            exemplaires_restants
        FROM VUE_CATALOGUE_LIVRES
        WHERE id_categorie = ? 
        """
        + filtre
        + """
        ORDER BY nom_livre
        """,
        parametres,
    ).fetchall()
    livres_formates = []
    for livre in livres:
        element = dict(livre)
        element["disponible"] = 1 if element["exemplaires_restants"] > 0 else 0
        livres_formates.append(element)
    return render_template("catalogue.html", categorie=categorie, livres=livres_formates, recherche=recherche)
@application.route("/cddvd")
def cddvd():
    base = bdd()
    assurer_colonne_image_cddvd(base)
    recherche = request.args.get("q", "").strip().lower()
    parametres = []
    filtre = ""
    if recherche:
        filtre = ' WHERE LOWER("nom_CD/DVD") LIKE ? OR LOWER("artiste_CD/DVD") LIKE ?'
        motif = "%" + recherche + "%"
        parametres = [motif, motif]
    liste_cddvd = base.execute(
        """
        SELECT "id_CD/DVD" AS id_cd_dvd, "nom_CD/DVD" AS nom_cd_dvd,
               "annee_CD/DVD" AS annee_cd_dvd, "artiste_CD/DVD" AS artiste_cd_dvd,
               image
        FROM "CD/DVD" 
        """
        + filtre
        + """
        ORDER BY "nom_CD/DVD"
        """,
        parametres,
    ).fetchall()
    return render_template("cddvd.html", cddvds=liste_cddvd, recherche=recherche)
@application.route("/reserver", methods=["GET", "POST"])
def reserver():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    message = None
    erreur = None
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero_cd_dvd = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero_cd_dvd:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero_cd_dvd:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        else:
            date_reservation = date.today()
            if isbn:
                livre = base.execute(
                    """
                    SELECT l.id_livre, l.nom_livre, l.ISBN_livre
                    FROM LIVRE l
                    WHERE CAST(l.ISBN_livre AS TEXT) = ?
                    ORDER BY l.id_livre LIMIT 1
                    """,
                    (isbn,),
                ).fetchone()
                if not livre:
                    erreur = "Livre introuvable pour cet ISBN."
                else:
                    id_reservation = prochain_identifiant(base, "RESERVATION", "id_reservation")
                    base.execute(
                        """
                        INSERT INTO RESERVATION
                        (id_reservation, date_reservation, date_de_retour, "id_client#", bibliotheque_retrait, date_limite_retour, date_retour_effective)
                        VALUES (?, ?, NULL, ?, 'Centre-ville', ?, NULL)
                        """,
                        (
                            id_reservation,
                            date_francaise(date_reservation),
                            session["utilisateur"]["id"],
                            date_francaise(date_reservation + timedelta(days=21)),
                        ),
                    )
                    base.execute(
                        """
                        INSERT INTO "LIGNE LIVRE" ("id_livre#", "id_reservation#")
                        VALUES (?, ?)
                        """,
                        (livre["id_livre"], id_reservation),
                    )
                    base.commit()
                    message = "Réservation enregistrée pour le livre : " + str(livre["nom_livre"])
            if numero_cd_dvd and not erreur:
                cd_dvd = base.execute(
                    """
                    SELECT "id_CD/DVD" AS id_cd_dvd, "nom_CD/DVD" AS nom_cd_dvd
                    FROM "CD/DVD"
                    WHERE "id_CD/DVD" = ?
                    """,
                    (numero_cd_dvd,),
                ).fetchone()
                if not cd_dvd:
                    erreur = "CD/DVD introuvable pour ce numéro."
                else:
                    id_reservation = prochain_identifiant(base, "RESERVATION", "id_reservation")
                    base.execute(
                        """
                        INSERT INTO RESERVATION
                        (id_reservation, date_reservation, date_de_retour, "id_client#", bibliotheque_retrait, date_limite_retour, date_retour_effective)
                        VALUES (?, ?, NULL, ?, 'Centre-ville', ?, NULL)
                        """,
                        (
                            id_reservation,
                            date_francaise(date_reservation),
                            session["utilisateur"]["id"],
                            date_francaise(date_reservation + timedelta(days=21)),
                        ),
                    )
                    base.execute(
                        """
                        INSERT INTO "LIGNE CD/DVD" ("id_CD/DVD#", "id_reservation#", date_de_retour)
                        VALUES (?, ?, NULL)
                        """,
                        (cd_dvd["id_cd_dvd"], id_reservation),
                    )
                    base.commit()
                    message = "Réservation enregistrée pour le CD/DVD : " + str(cd_dvd["nom_cd_dvd"])
    historique = base.execute(
        """
        SELECT
            type_media,
            id_reservation,
            nom_media,
            reference_media,
            date_reservation,
            date_limite_retour,
            date_retour_effective
        FROM VUE_HISTORIQUE_RESERVATIONS
        WHERE id_client = ?
        ORDER BY id_reservation DESC
        """,
        (session["utilisateur"]["id"],),
    ).fetchall()
    return render_template("reserver.html", message=message, erreur=erreur, historique=historique)
@application.route("/mes_reservations")
def mes_reservations():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    reservations = base.execute(
        """
        SELECT
            type_media,
            id_reservation,
            nom_media,
            auteur_media,
            reference_media,
            date_reservation,
            date_limite_retour,
            bibliotheque_retrait,
            date_retour_effective
        FROM VUE_MES_RESERVATIONS
        WHERE id_client = ?
        ORDER BY id_reservation DESC
        """,
        (session["utilisateur"]["id"],),
    ).fetchall()
    return render_template("mes_reservations.html", reservations=reservations)
@application.route("/rendre", methods=["GET", "POST"])
def rendre():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    message = None
    erreur = None
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero_cd_dvd = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero_cd_dvd:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero_cd_dvd:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        else:
            if isbn:
                ligne_livre = base.execute(
                    """
                    SELECT r.id_reservation, l.nom_livre
                    FROM RESERVATION r
                    JOIN "LIGNE LIVRE" ll ON ll."id_reservation#" = r.id_reservation
                    JOIN LIVRE l ON l.id_livre = ll."id_livre#"
                    WHERE r."id_client#" = ? AND CAST(l.ISBN_livre AS TEXT) = ? AND r.date_retour_effective IS NULL
                    ORDER BY r.id_reservation DESC LIMIT 1
                    """,
                    (session["utilisateur"]["id"], isbn),
                ).fetchone()
                if not ligne_livre:
                    erreur = "Aucune réservation active pour cet ISBN."
                else:
                    base.execute(
                        "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                        (date_francaise(date.today()), date_francaise(date.today()), ligne_livre["id_reservation"]),
                    )
                    base.commit()
                    message = "Retour enregistré pour le livre : " + str(ligne_livre["nom_livre"])
            if numero_cd_dvd and not erreur:
                ligne_cd_dvd = base.execute(
                    """
                    SELECT r.id_reservation, c."nom_CD/DVD" AS nom_cd_dvd
                    FROM RESERVATION r
                    JOIN "LIGNE CD/DVD" lcd ON lcd."id_reservation#" = r.id_reservation
                    JOIN "CD/DVD" c ON c."id_CD/DVD" = lcd."id_CD/DVD#"
                    WHERE r."id_client#" = ? AND lcd."id_CD/DVD#" = ? AND r.date_retour_effective IS NULL
                    ORDER BY r.id_reservation DESC LIMIT 1
                    """,
                    (session["utilisateur"]["id"], numero_cd_dvd),
                ).fetchone()
                if not ligne_cd_dvd:
                    erreur = "Aucune réservation active pour ce numéro CD/DVD."
                else:
                    base.execute(
                        "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                        (date_francaise(date.today()), date_francaise(date.today()), ligne_cd_dvd["id_reservation"]),
                    )
                    base.execute(
                        'UPDATE "LIGNE CD/DVD" SET date_de_retour=? WHERE "id_reservation#"=?',
                        (date_francaise(date.today()), ligne_cd_dvd["id_reservation"]),
                    )
                    base.commit()
                    message = "Retour enregistré pour le CD/DVD : " + str(ligne_cd_dvd["nom_cd_dvd"])
    return render_template("rendre.html", message=message, erreur=erreur)
@application.route("/connexion", methods=["GET", "POST"])
def connexion():
    base = bdd()
    erreur = None
    prochain = request.values.get("next") or url_for("accueil")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("password", "")
        if email == "administrateur" and mot_de_passe == "secret":
            session["admin"] = True
            return redirect(url_for("admin"))
        utilisateur = base.execute(
            "SELECT * FROM CLIENT WHERE LOWER(adressemail_client)=? AND mot_de_passe IS NOT NULL",
            (email,),
        ).fetchone()
        if not utilisateur:
            erreur = "Adresse e-mail introuvable."
        elif not check_password_hash(utilisateur["mot_de_passe"], mot_de_passe):
            erreur = "Mot de passe incorrect."
        else:
            session["utilisateur"] = {
                "id": utilisateur["id_client"],
                "prenom": utilisateur["prenom_client"],
                "nom_utilisateur": utilisateur["nom_utilisateur"],
                "email": utilisateur["adressemail_client"],
            }
            ajouter_log_connexion(utilisateur["id_client"])
            return redirect(prochain)
    return render_template("connexion.html", erreur=erreur, prochain=prochain)
@application.route("/creer_compte", methods=["POST"])
def creer_compte():
    base = bdd()
    prochain = request.form.get("next") or url_for("accueil")
    donnees = {
        "prenom_client": request.form.get("prenom", "").strip(),
        "nom_utilisateur": request.form.get("nom_utilisateur", "").strip(),
        "date_naissance": request.form.get("date_naissance", "").strip(),
        "code_postal": request.form.get("code_postal", "").strip(),
        "adressemail_client": request.form.get("email", "").strip().lower(),
        "mot_de_passe": request.form.get("password", ""),
    }
    if not all(donnees.values()):
        return render_template("connexion.html", erreur="Tous les champs sont obligatoires.", prochain=prochain)
    deja_existant = base.execute(
        """
        SELECT 1
        FROM CLIENT
        WHERE LOWER(adressemail_client)=? OR LOWER(COALESCE(nom_utilisateur, ''))=?
        LIMIT 1
        """,
        (donnees["adressemail_client"], donnees["nom_utilisateur"].lower()),
    ).fetchone()
    if deja_existant:
        return render_template(
            "connexion.html",
            erreur="Cet e-mail ou ce nom d'utilisateur existe déjà.",
            prochain=prochain,
        )
    try:
        prochain_id_client = prochain_identifiant(base, "CLIENT", "id_client")
        base.execute(
            """
            INSERT INTO CLIENT
            (id_client, nom_client, prenom_client, adressepostale_client, adressemail_client, date_naissance_client, telephone_client, nom_utilisateur, mot_de_passe, date_creation, code_postal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prochain_id_client,
                donnees["nom_utilisateur"],
                donnees["prenom_client"],
                donnees["code_postal"],
                donnees["adressemail_client"],
                donnees["date_naissance"],
                None,
                donnees["nom_utilisateur"],
                generate_password_hash(donnees["mot_de_passe"]),
                date_francaise(date.today()),
                donnees["code_postal"],
            ),
        )
        base.commit()
    except sqlite3.IntegrityError:
        return render_template(
            "connexion.html",
            erreur="Cet e-mail ou ce nom d'utilisateur existe déjà.",
            prochain=prochain,
        )
    utilisateur = base.execute(
        "SELECT * FROM CLIENT WHERE LOWER(adressemail_client)=?",
        (donnees["adressemail_client"],),
    ).fetchone()
    session["utilisateur"] = {
        "id": utilisateur["id_client"],
        "prenom": utilisateur["prenom_client"],
        "nom_utilisateur": utilisateur["nom_utilisateur"],
        "email": utilisateur["adressemail_client"],
    }
    ajouter_log_connexion(utilisateur["id_client"])
    return redirect(prochain)
@application.route("/autres")
@application.route("/statistiques")
def autres():
    base = bdd()
    image_graphe = None
    info_graphe = "Graphique indisponible."
    try:
        import matplotlib.pyplot as plt
        lignes = base.execute("SELECT strftime('%H', date_connexion) h, COUNT(*) n FROM CONNEXION_LOG GROUP BY h ORDER BY h").fetchall()
        # Affichage réaliste: uniquement sur les heures d'ouverture, avec un plafond.
        x = []
        y = []
        for ligne in lignes:
            if ligne["h"] is None:
                continue
            heure = int(ligne["h"])
            if heure < 8 or heure > 20:
                continue
            x.append("%02d" % heure)
            y.append(min(int(ligne["n"]), 39))
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.bar(x, y, color="#1f5e84")
        ax.set_title("Connexions par heure")
        tampon = BytesIO()
        fig.tight_layout()
        fig.savefig(tampon, format="png")
        plt.close(fig)
        image_graphe = base64.b64encode(tampon.getvalue()).decode("ascii")
    except Exception:
        pass
    nb_clients_web = base.execute("SELECT COUNT(*) AS total FROM CLIENT WHERE mot_de_passe IS NOT NULL").fetchone()["total"]
    nb_clients_base = base.execute("SELECT COUNT(*) AS total FROM CLIENT").fetchone()["total"]
    nb_livres_actifs = base.execute(
        'SELECT COUNT(*) AS total FROM RESERVATION r JOIN "LIGNE LIVRE" ll ON ll."id_reservation#" = r.id_reservation WHERE r.date_retour_effective IS NULL'
    ).fetchone()["total"]
    nb_cddvd_actifs = base.execute(
        'SELECT COUNT(*) AS total FROM RESERVATION r JOIN "LIGNE CD/DVD" lcd ON lcd."id_reservation#" = r.id_reservation WHERE r.date_retour_effective IS NULL'
    ).fetchone()["total"]
    top_livres = base.execute(
        """
        SELECT
            l.nom_livre,
            c.nom_categorie,
            COUNT(*) AS nb_demandes
        FROM RESERVATION r
        JOIN "LIGNE LIVRE" ll ON ll."id_reservation#" = r.id_reservation
        JOIN LIVRE l ON l.id_livre = ll."id_livre#"
        JOIN CATEGORIE c ON c.id_categorie = l.id_categorie
        GROUP BY l.id_livre, l.nom_livre, c.nom_categorie
        ORDER BY nb_demandes DESC, l.nom_livre ASC
        LIMIT 10
        """
    ).fetchall()
    top_livres_formates = []
    for ligne in top_livres:
        item = dict(ligne)
        item["slug_categorie"] = faire_slug(item["nom_categorie"])
        top_livres_formates.append(item)
    return render_template(
        "autres.html",
        graph_image=image_graphe,
        graph_info=info_graphe,
        nb_clients_web=nb_clients_web,
        nb_clients_initial=nb_clients_base,
        nb_reservations_actives=nb_livres_actifs + nb_cddvd_actifs,
        top_livres_demandes=top_livres_formates,
    )
def assurer_table_historique_suppressions(base):
    base.execute(
        """
        CREATE TABLE IF NOT EXISTS SUPPRESSION_LOG (
            id_suppression INTEGER PRIMARY KEY AUTOINCREMENT,
            type_media TEXT NOT NULL,
            reference_media TEXT NOT NULL,
            titre_media TEXT,
            auteur_media TEXT,
            annee_media TEXT,
            id_ligne_origine TEXT,
            payload_json TEXT NOT NULL,
            date_suppression TEXT NOT NULL,
            restaure INTEGER NOT NULL DEFAULT 0,
            date_restauration TEXT
        )
        """
    )
    base.commit()
def assurer_colonne_total_exemplaires_livre(base):
    colonnes = [ligne["name"] for ligne in base.execute("PRAGMA table_info('LIVRE')").fetchall()]
    if "total_exemplaires" not in colonnes:
        base.execute("ALTER TABLE LIVRE ADD COLUMN total_exemplaires INTEGER")
        base.execute("UPDATE LIVRE SET total_exemplaires = 1 WHERE total_exemplaires IS NULL")
        base.commit()
def assurer_colonne_image_cddvd(base):
    colonnes = [ligne["name"] for ligne in base.execute('PRAGMA table_info("CD/DVD")').fetchall()]
    if "image" not in colonnes:
        base.execute('ALTER TABLE "CD/DVD" ADD COLUMN image TEXT')
        base.commit()
@application.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("connexion", next=url_for("admin")))
    base = bdd()
    assurer_table_historique_suppressions(base)
    assurer_colonne_image_cddvd(base)
    assurer_colonne_total_exemplaires_livre(base)
    erreur = None
    message = None
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "ajouter":
            nom_livre = request.form.get("nom_livre", "").strip()
            auteur_livre = request.form.get("auteur_livre", "").strip()
            maison_edition = request.form.get("maison_edition_livre", "").strip()
            annee = request.form.get("annee_livre", "").strip()
            id_categorie = request.form.get("id_categorie", "").strip()
            isbn_livre = request.form.get("isbn_livre", "").strip()
            resume = request.form.get("resume", "").strip()
            nom_image_livre = request.form.get("nom_image_livre", "").strip()
            fichier_image_livre = request.files.get("image_fichier_livre")
            image = request.form.get("image", "").strip() or None
            if not nom_livre or not auteur_livre or not id_categorie or not isbn_livre:
                erreur = "Nom, auteur, catégorie et ISBN sont obligatoires."
            else:
                try:
                    image_upload = enregistrer_image_upload(fichier_image_livre, nom_image_livre)
                    image_finale = image_upload or image
                    base.execute(
                        """
                        INSERT INTO LIVRE
                        (nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            nom_livre,
                            auteur_livre,
                            maison_edition,
                            int(annee) if annee else None,
                            int(id_categorie),
                            isbn_livre,
                            resume,
                            image_finale,
                            3,
                        ),
                    )
                    base.commit()
                    message = "Livre ajouté."
                except Exception as e:
                    erreur = "Ajout impossible : " + str(e)
        if action == "ajouter_cddvd":
            nom_cd_dvd = request.form.get("nom_cd_dvd", "").strip()
            artiste_cd_dvd = request.form.get("artiste_cd_dvd", "").strip()
            annee_cd_dvd = request.form.get("annee_cd_dvd", "").strip()
            numero_cd_dvd = request.form.get("id_cd_dvd", "").strip()
            nom_image_cddvd = request.form.get("nom_image_cddvd", "").strip()
            fichier_image_cddvd = request.files.get("image_fichier_cddvd")
            image_cddvd = request.form.get("image_cddvd", "").strip() or None
            if not nom_cd_dvd:
                erreur = "Le nom du CD/DVD est obligatoire."
            else:
                try:
                    image_upload_cddvd = enregistrer_image_upload(fichier_image_cddvd, nom_image_cddvd)
                    image_finale_cddvd = image_upload_cddvd or image_cddvd
                    if numero_cd_dvd:
                        deja_present = base.execute(
                            'SELECT 1 FROM "CD/DVD" WHERE "id_CD/DVD" = ?',
                            (numero_cd_dvd,),
                        ).fetchone()
                        if deja_present:
                            erreur = "Ce numéro CD/DVD existe déjà."
                        else:
                            base.execute(
                                """
                                INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    int(numero_cd_dvd),
                                    nom_cd_dvd,
                                    int(annee_cd_dvd) if annee_cd_dvd else None,
                                    artiste_cd_dvd or None,
                                    image_finale_cddvd,
                                ),
                            )
                    else:
                        prochain_numero = base.execute(
                            'SELECT COALESCE(MAX(CAST("id_CD/DVD" AS INTEGER)), 0) + 1 AS prochain FROM "CD/DVD"'
                        ).fetchone()["prochain"]
                        base.execute(
                            """
                            INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                int(prochain_numero),
                                nom_cd_dvd,
                                int(annee_cd_dvd) if annee_cd_dvd else None,
                                artiste_cd_dvd or None,
                                image_finale_cddvd,
                            ),
                        )
                    if not erreur:
                        base.commit()
                        message = "CD/DVD ajouté."
                except Exception as e:
                    erreur = "Ajout CD/DVD impossible : " + str(e)
        elif action == "supprimer":
            isbn_livre = request.form.get("isbn_livre_suppression", "").strip()
            numero_cd_dvd = request.form.get("numero_cd_dvd_suppression", "").strip()
            if not isbn_livre and not numero_cd_dvd:
                erreur = "Entre un ISBN livre ou un numéro CD/DVD."
            elif isbn_livre and numero_cd_dvd:
                erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
            elif isbn_livre:
                actif = base.execute(
                    """
                    SELECT 1
                    FROM RESERVATION r
                    JOIN "LIGNE LIVRE" ll ON ll."id_reservation#" = r.id_reservation
                    JOIN LIVRE l ON l.id_livre = ll."id_livre#"
                    WHERE CAST(l.ISBN_livre AS TEXT) = ? AND r.date_retour_effective IS NULL
                    LIMIT 1
                    """,
                    (isbn_livre,),
                ).fetchone()
                if actif:
                    erreur = "Suppression impossible : livre actuellement réservé."
                else:
                    livres = base.execute(
                        """
                        SELECT
                            id_livre,
                            nom_livre,
                            auteur_livre,
                            maison_edition_livre,
                            annee_livre,
                            id_categorie,
                            ISBN_livre,
                            resume,
                            image,
                            total_exemplaires
                        FROM LIVRE
                        WHERE CAST(ISBN_livre AS TEXT) = ?
                        """,
                        (isbn_livre,),
                    ).fetchall()
                    if not livres:
                        erreur = "Aucun livre trouvé pour cet ISBN."
                    else:
                        date_suppression = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for livre in livres:
                            payload = {
                                "id_livre": livre["id_livre"],
                                "nom_livre": livre["nom_livre"],
                                "auteur_livre": livre["auteur_livre"],
                                "maison_edition_livre": livre["maison_edition_livre"],
                                "annee_livre": livre["annee_livre"],
                                "id_categorie": livre["id_categorie"],
                                "ISBN_livre": str(livre["ISBN_livre"]),
                                "resume": livre["resume"],
                                "image": livre["image"],
                                "stock_total": int(livre["total_exemplaires"] or 1),
                            }
                            base.execute(
                                """
                                INSERT INTO SUPPRESSION_LOG
                                (type_media, reference_media, titre_media, auteur_media, annee_media, id_ligne_origine, payload_json, date_suppression)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    "livre",
                                    str(livre["ISBN_livre"]),
                                    livre["nom_livre"],
                                    livre["auteur_livre"],
                                    str(livre["annee_livre"]) if livre["annee_livre"] is not None else "",
                                    str(livre["id_livre"]),
                                    json.dumps(payload, ensure_ascii=True),
                                    date_suppression,
                                ),
                            )
                        base.execute(
                            "DELETE FROM LIVRE WHERE CAST(ISBN_livre AS TEXT) = ?",
                            (isbn_livre,),
                        )
                        base.commit()
                        message = str(len(livres)) + " livre(s) supprimé(s)."
            else:
                actif = base.execute(
                    """
                    SELECT 1
                    FROM RESERVATION r
                    JOIN "LIGNE CD/DVD" lcd ON lcd."id_reservation#" = r.id_reservation
                    WHERE lcd."id_CD/DVD#" = ? AND r.date_retour_effective IS NULL
                    LIMIT 1
                    """,
                    (numero_cd_dvd,),
                ).fetchone()
                if actif:
                    erreur = "Suppression impossible : CD/DVD actuellement réservé."
                else:
                    cd_dvd = base.execute(
                        """
                        SELECT
                            "id_CD/DVD" AS id_cd_dvd,
                            "nom_CD/DVD" AS nom_cd_dvd,
                            "annee_CD/DVD" AS annee_cd_dvd,
                            "artiste_CD/DVD" AS artiste_cd_dvd,
                            image
                        FROM "CD/DVD"
                        WHERE "id_CD/DVD" = ?
                        """,
                        (numero_cd_dvd,),
                    ).fetchone()
                    if not cd_dvd:
                        erreur = "Aucun CD/DVD trouvé pour ce numéro."
                    else:
                        payload = {
                            "id_cd_dvd": cd_dvd["id_cd_dvd"],
                            "nom_cd_dvd": cd_dvd["nom_cd_dvd"],
                            "annee_cd_dvd": cd_dvd["annee_cd_dvd"],
                            "artiste_cd_dvd": cd_dvd["artiste_cd_dvd"],
                            "image": cd_dvd["image"],
                        }
                        base.execute(
                            """
                            INSERT INTO SUPPRESSION_LOG
                            (type_media, reference_media, titre_media, auteur_media, annee_media, id_ligne_origine, payload_json, date_suppression)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "cddvd",
                                str(cd_dvd["id_cd_dvd"]),
                                cd_dvd["nom_cd_dvd"],
                                cd_dvd["artiste_cd_dvd"],
                                str(cd_dvd["annee_cd_dvd"]) if cd_dvd["annee_cd_dvd"] is not None else "",
                                str(cd_dvd["id_cd_dvd"]),
                                json.dumps(payload, ensure_ascii=True),
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            ),
                        )
                        base.execute(
                            'DELETE FROM "CD/DVD" WHERE "id_CD/DVD" = ?',
                            (numero_cd_dvd,),
                        )
                        base.commit()
                        message = "CD/DVD supprimé."
        elif action == "restaurer":
            id_suppression = request.form.get("id_suppression", "").strip()
            if not id_suppression:
                erreur = "Suppression à restaurer introuvable."
            else:
                suppression = base.execute(
                    "SELECT * FROM SUPPRESSION_LOG WHERE id_suppression = ? AND restaure = 0",
                    (id_suppression,),
                ).fetchone()
                if not suppression:
                    erreur = "Cet élément est déjà restauré ou introuvable."
                else:
                    try:
                        payload = json.loads(suppression["payload_json"])
                    except json.JSONDecodeError:
                        payload = None
                    if not payload:
                        erreur = "Historique invalide, restauration impossible."
                    else:
                        try:
                            if suppression["type_media"] == "livre":
                                try:
                                    base.execute(
                                        """
                                        INSERT INTO LIVRE
                                        (id_livre, nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            payload.get("id_livre"),
                                            payload.get("nom_livre"),
                                            payload.get("auteur_livre"),
                                            payload.get("maison_edition_livre"),
                                            payload.get("annee_livre"),
                                            payload.get("id_categorie"),
                                            payload.get("ISBN_livre"),
                                            payload.get("resume"),
                                            payload.get("image"),
                                            int(payload.get("stock_total") or 1),
                                        ),
                                    )
                                except sqlite3.IntegrityError:
                                    base.execute(
                                        """
                                        INSERT INTO LIVRE
                                        (nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            payload.get("nom_livre"),
                                            payload.get("auteur_livre"),
                                            payload.get("maison_edition_livre"),
                                            payload.get("annee_livre"),
                                            payload.get("id_categorie"),
                                            payload.get("ISBN_livre"),
                                            payload.get("resume"),
                                            payload.get("image"),
                                            int(payload.get("stock_total") or 1),
                                        ),
                                    )
                                message = "Livre restauré."
                            else:
                                try:
                                    base.execute(
                                        """
                                        INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image)
                                        VALUES (?, ?, ?, ?, ?)
                                        """,
                                        (
                                            payload.get("id_cd_dvd"),
                                            payload.get("nom_cd_dvd"),
                                            payload.get("annee_cd_dvd"),
                                            payload.get("artiste_cd_dvd"),
                                            payload.get("image"),
                                        ),
                                    )
                                except sqlite3.IntegrityError:
                                    prochain_numero = base.execute(
                                        'SELECT COALESCE(MAX(CAST("id_CD/DVD" AS INTEGER)), 0) + 1 AS prochain FROM "CD/DVD"'
                                    ).fetchone()["prochain"]
                                    base.execute(
                                        """
                                        INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image)
                                        VALUES (?, ?, ?, ?, ?)
                                        """,
                                        (
                                            int(prochain_numero),
                                            payload.get("nom_cd_dvd"),
                                            payload.get("annee_cd_dvd"),
                                            payload.get("artiste_cd_dvd"),
                                            payload.get("image"),
                                        ),
                                    )
                                message = "CD/DVD restauré."
                            base.execute(
                                """
                                UPDATE SUPPRESSION_LOG
                                SET restaure = 1, date_restauration = ?
                                WHERE id_suppression = ?
                                """,
                                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), id_suppression),
                            )
                            base.commit()
                        except Exception as e:
                            erreur = "Restauration impossible : " + str(e)
    categories = base.execute("SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie").fetchall()
    suggestions_images_livres = {}
    for cat in categories:
        suggestions_images_livres[str(cat["id_categorie"])] = prochain_nom_image_livre(base, cat["id_categorie"])
    suggestion_image_cddvd = prochain_nom_image_cddvd(base)
    recherche_suppression = request.args.get("q_supp", "").strip().lower()
    voir_plus = request.args.get("voir", "").strip() == "1"
    filtre = ""
    parametres = []
    if recherche_suppression:
        filtre = """
            AND (
                LOWER(COALESCE(titre_media, '')) LIKE ?
                OR LOWER(COALESCE(auteur_media, '')) LIKE ?
                OR LOWER(COALESCE(reference_media, '')) LIKE ?
                OR LOWER(COALESCE(type_media, '')) LIKE ?
            )
        """
        motif = "%" + recherche_suppression + "%"
        parametres = [motif, motif, motif, motif]
    limite = 120 if voir_plus else 8
    suppressions = base.execute(
        """
        SELECT
            id_suppression,
            type_media,
            reference_media,
            titre_media,
            auteur_media,
            annee_media,
            date_suppression
        FROM SUPPRESSION_LOG
        WHERE restaure = 0
        ORDER BY id_suppression DESC
        LIMIT ?
        """
        + filtre
        + """
        """,
        [*parametres, limite],
    ).fetchall()
    total_suppressions = base.execute(
        """
        SELECT COUNT(*) AS total
        FROM SUPPRESSION_LOG
        WHERE restaure = 0
        """
        + filtre
        + """
        """,
        parametres,
    ).fetchone()["total"]
    return render_template(
        "admin.html",
        categories=categories,
        suggestions_images_livres=suggestions_images_livres,
        suggestion_image_cddvd=suggestion_image_cddvd,
        suppressions=suppressions,
        recherche_suppression=recherche_suppression,
        voir_plus=voir_plus,
        total_suppressions=total_suppressions,
        erreur=erreur,
        message=message,
    )
@application.route("/deconnexion")
def deconnexion():
    session.pop("utilisateur", None)
    session.pop("admin", None)
    return redirect(url_for("accueil"))
if __name__ == "__main__":
    application.run(debug=True)

