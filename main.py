from datetime import date, timedelta
import sqlite3
from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
application = Flask(__name__)
application.secret_key = "cle_secrete_bibliotheque"
BASE_DONNEES = "bibliotheque.db"
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
def date_francaise(valeur):
    return valeur.strftime("%d/%m/%Y")
def prochain_identifiant(base, table, colonne):
    sql = (
        'SELECT COALESCE(MAX(CAST("' + colonne + '" AS INTEGER)), 0) + 1 AS prochain '
        + 'FROM "' + table + '"'
    )
    return int(base.execute(sql).fetchone()["prochain"])
def faire_slug(texte):
    return "-".join(str(texte).strip().lower().split())
def categories_menu():
    try:
        lignes = bdd().execute(
            "SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie"
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": l["id_categorie"],
            "nom": l["nom_categorie"],
            "slug": faire_slug(l["nom_categorie"]),
        }
        for l in lignes
    ]
def verifier_connexion():
    if "utilisateur" not in session:
        return redirect(url_for("connexion", next=request.path))
    return None
@application.context_processor
def contexte_global():
    return {
        "utilisateur": session.get("utilisateur"),
        "admin_connecte": bool(session.get("admin")),
        "menu_categories": categories_menu(),
    }
@application.route("/")
def accueil():
    nom = session.get("utilisateur", {}).get("prenom", "")
    return render_template("principal.html", nomutlisateur=nom)
@application.route("/catalogue/<slug>")
def catalogue(slug):
    base = bdd()
    recherche = request.args.get("q", "").strip().lower()
    categorie = base.execute(
        "SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie"
    ).fetchall()
    categorie = next((c for c in categorie if faire_slug(c["nom_categorie"]) == slug), None)
    if not categorie:
        return redirect(url_for("accueil"))
    params = [categorie["id_categorie"]]
    filtre = ""
    if recherche:
        motif = "%" + recherche + "%"
        filtre = " AND (LOWER(nom_livre) LIKE ? OR LOWER(auteur_livre) LIKE ? OR CAST(ISBN_livre AS TEXT) LIKE ?)"
        params.extend([motif, motif, motif])
    livres = [
        dict(x)
        for x in base.execute(
            """
            SELECT
                id_livre,
                nom_livre,
                auteur_livre,
                CAST(ISBN_livre AS TEXT) AS ISBN_livre,
                resume,
                image,
                COALESCE(total_exemplaires, 1) AS total_exemplaires,
                COALESCE(total_exemplaires, 1) AS exemplaires_restants
            FROM LIVRE
            WHERE id_categorie = ?
            """
            + filtre
            + " ORDER BY nom_livre",
            params,
        ).fetchall()
    ]
    for l in livres:
        l["disponible"] = 1 if int(l["exemplaires_restants"] or 0) > 0 else 0
    return render_template(
        "catalogue.html",
        categorie={"id": categorie["id_categorie"], "nom": categorie["nom_categorie"], "slug": slug},
        livres=livres,
        recherche=recherche,
    )
@application.route("/cddvd")
def cddvd():
    base = bdd()
    recherche = request.args.get("q", "").strip().lower()
    params = []
    filtre = ""
    if recherche:
        motif = "%" + recherche + "%"
        filtre = ' WHERE LOWER(c."nom_CD/DVD") LIKE ? OR LOWER(COALESCE(c."artiste_CD/DVD", \"\")) LIKE ?'
        params = [motif, motif]
    cddvds = [
        dict(x)
        for x in base.execute(
            """
            SELECT
                c."id_CD/DVD" AS id_cd_dvd,
                c."nom_CD/DVD" AS nom_cd_dvd,
                c."annee_CD/DVD" AS annee_cd_dvd,
                c."artiste_CD/DVD" AS artiste_cd_dvd,
                c.image,
                COALESCE(c.total_exemplaires, 1) AS total_exemplaires,
                COALESCE(c.total_exemplaires, 1) AS exemplaires_restants
            FROM "CD/DVD" c
            """
            + filtre
            + ' ORDER BY c."nom_CD/DVD"',
            params,
        ).fetchall()
    ]
    return render_template("cddvd.html", cddvds=cddvds, recherche=recherche)
@application.route("/reserver", methods=["GET", "POST"])
def reserver():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    message = None
    erreur = None
    uid = session["utilisateur"]["id"]
    def creer_resa():
        rid = prochain_identifiant(base, "RESERVATION", "id_reservation")
        auj = date.today()
        base.execute(
            'INSERT INTO RESERVATION (id_reservation, date_reservation, date_de_retour, "id_client#", bibliotheque_retrait, date_limite_retour, date_retour_effective) VALUES (?, ?, NULL, ?, "Centre-ville", ?, NULL)',
            (rid, date_francaise(auj), uid, date_francaise(auj + timedelta(days=21))),
        )
        return rid
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        elif isbn:
            livre = base.execute(
                'SELECT id_livre, nom_livre FROM LIVRE WHERE CAST(ISBN_livre AS TEXT)=? ORDER BY id_livre LIMIT 1',
                (isbn,),
            ).fetchone()
            if not livre:
                erreur = "Livre introuvable pour cet ISBN."
            else:
                rid = creer_resa()
                base.execute('INSERT INTO "LIGNE LIVRE" ("id_livre#", "id_reservation#") VALUES (?, ?)', (livre["id_livre"], rid))
                base.commit()
                message = "Réservation enregistrée pour le livre : " + str(livre["nom_livre"])
        else:
            cd = base.execute(
                'SELECT "id_CD/DVD" AS id_cd_dvd, "nom_CD/DVD" AS nom_cd_dvd FROM "CD/DVD" WHERE "id_CD/DVD"=?',
                (numero,),
            ).fetchone()
            if not cd:
                erreur = "CD/DVD introuvable pour ce numéro."
            else:
                rid = creer_resa()
                base.execute(
                    'INSERT INTO "LIGNE CD/DVD" ("id_CD/DVD#", "id_reservation#", date_de_retour) VALUES (?, ?, NULL)',
                    (cd["id_cd_dvd"], rid),
                )
                base.commit()
                message = "Réservation enregistrée pour le CD/DVD : " + str(cd["nom_cd_dvd"])
    historique = bdd().execute(
        """
        SELECT type_media, id_reservation, nom_media, reference_media, date_reservation, date_limite_retour, date_retour_effective
        FROM VUE_HISTORIQUE_RESERVATIONS
        WHERE id_client = ?
        ORDER BY id_reservation DESC
        """,
        (uid,),
    ).fetchall()
    return render_template("reserver.html", message=message, erreur=erreur, historique=historique)
@application.route("/mes_reservations")
def mes_reservations():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    reservations = bdd().execute(
        """
        SELECT type_media, id_reservation, nom_media, auteur_media, reference_media, date_reservation, date_limite_retour, bibliotheque_retrait, date_retour_effective
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
    uid = session["utilisateur"]["id"]
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        elif isbn:
            resa = base.execute(
                'SELECT r.id_reservation, l.nom_livre FROM RESERVATION r JOIN "LIGNE LIVRE" ll ON ll."id_reservation#"=r.id_reservation JOIN LIVRE l ON l.id_livre=ll."id_livre#" WHERE r."id_client#"=? AND CAST(l.ISBN_livre AS TEXT)=? AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1',
                (uid, isbn),
            ).fetchone()
            if not resa:
                erreur = "Aucune réservation active pour cet ISBN."
            else:
                base.execute(
                    "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                    (date_francaise(date.today()), date_francaise(date.today()), resa["id_reservation"]),
                )
                base.commit()
                message = "Retour enregistré pour le livre : " + str(resa["nom_livre"])
        else:
            resa = base.execute(
                'SELECT r.id_reservation, c."nom_CD/DVD" AS nom_cd_dvd FROM RESERVATION r JOIN "LIGNE CD/DVD" lcd ON lcd."id_reservation#"=r.id_reservation JOIN "CD/DVD" c ON c."id_CD/DVD"=lcd."id_CD/DVD#" WHERE r."id_client#"=? AND lcd."id_CD/DVD#"=? AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1',
                (uid, numero),
            ).fetchone()
            if not resa:
                erreur = "Aucune réservation active pour ce numéro CD/DVD."
            else:
                base.execute(
                    "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                    (date_francaise(date.today()), date_francaise(date.today()), resa["id_reservation"]),
                )
                base.execute(
                    'UPDATE "LIGNE CD/DVD" SET date_de_retour=? WHERE "id_reservation#"=?',
                    (date_francaise(date.today()), resa["id_reservation"]),
                )
                base.commit()
                message = "Retour enregistré pour le CD/DVD : " + str(resa["nom_cd_dvd"])
    return render_template("rendre.html", message=message, erreur=erreur)
@application.route("/connexion", methods=["GET", "POST"])
def connexion():
    base = bdd()
    erreur = None
    prochain = request.values.get("next") or url_for("accueil")
    if request.method == "POST":
        identifiant = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("password", "")
        utilisateur = base.execute(
            "SELECT * FROM CLIENT WHERE (LOWER(adressemail_client)=? OR LOWER(COALESCE(nom_utilisateur,''))=?) AND mot_de_passe IS NOT NULL LIMIT 1",
            (identifiant, identifiant),
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
            est_admin = base.execute(
                "SELECT 1 FROM WEB_ADMIN WHERE LOWER(nom_utilisateur)=? LIMIT 1",
                (str(utilisateur["nom_utilisateur"]).lower(),),
            ).fetchone()
            if est_admin:
                session["admin"] = True
                return redirect(url_for("admin"))
            session.pop("admin", None)
            return redirect(prochain)
    return render_template("connexion.html", erreur=erreur, prochain=prochain)
@application.route("/creer_compte", methods=["POST"])
def creer_compte():
    base = bdd()
    prochain = request.form.get("next") or url_for("accueil")
    prenom = request.form.get("prenom", "").strip()
    nom_utilisateur = request.form.get("nom_utilisateur", "").strip()
    date_naissance = request.form.get("date_naissance", "").strip()
    code_postal = request.form.get("code_postal", "").strip()
    email = request.form.get("email", "").strip().lower()
    mot_de_passe = request.form.get("password", "")
    if not all([prenom, nom_utilisateur, date_naissance, code_postal, email, mot_de_passe]):
        return render_template("connexion.html", erreur="Tous les champs sont obligatoires.", prochain=prochain)
    deja = base.execute(
        "SELECT 1 FROM CLIENT WHERE LOWER(adressemail_client)=? OR LOWER(COALESCE(nom_utilisateur,''))=? LIMIT 1",
        (email, nom_utilisateur.lower()),
    ).fetchone()
    if deja:
        return render_template("connexion.html", erreur="Cet e-mail ou ce nom d'utilisateur existe déjà.", prochain=prochain)
    try:
        mdp_hash = generate_password_hash("lisette") if nom_utilisateur.lower() == "admin" else generate_password_hash(mot_de_passe)
        cid = prochain_identifiant(base, "CLIENT", "id_client")
        base.execute(
            'INSERT INTO CLIENT (id_client, nom_client, prenom_client, adressepostale_client, adressemail_client, date_naissance_client, telephone_client, nom_utilisateur, mot_de_passe, date_creation, code_postal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (cid, nom_utilisateur, prenom, code_postal, email, date_naissance, None, nom_utilisateur, mdp_hash, date_francaise(date.today()), code_postal),
        )
        if nom_utilisateur.lower() == "admin":
            adm = base.execute("SELECT id_admin FROM WEB_ADMIN WHERE LOWER(nom_utilisateur)=? LIMIT 1", ("admin",)).fetchone()
            if adm:
                base.execute("UPDATE WEB_ADMIN SET mot_de_passe_hash=? WHERE id_admin=?", (mdp_hash, adm["id_admin"]))
            else:
                base.execute("INSERT INTO WEB_ADMIN (nom_utilisateur, mot_de_passe_hash) VALUES (?, ?)", ("admin", mdp_hash))
        base.commit()
    except sqlite3.IntegrityError:
        return render_template("connexion.html", erreur="Cet e-mail ou ce nom d'utilisateur existe déjà.", prochain=prochain)
    session["utilisateur"] = {"id": cid, "prenom": prenom, "nom_utilisateur": nom_utilisateur, "email": email}
    if nom_utilisateur.lower() == "admin":
        session["admin"] = True
        return redirect(url_for("admin"))
    return redirect(prochain)
@application.route("/autres")
@application.route("/statistiques")
def autres():
    base = bdd()
    nb_clients = int(base.execute("SELECT COUNT(*) AS total FROM CLIENT").fetchone()["total"])
    nb_actives = int(
        base.execute("SELECT COUNT(*) AS total FROM RESERVATION WHERE date_retour_effective IS NULL").fetchone()["total"]
    )
    return render_template(
        "autres.html",
        graph_image=None,
        graph_info="Graphique non activé.",
        nb_clients_web=nb_clients,
        nb_clients_initial=nb_clients,
        nb_reservations_actives=nb_actives,
        top_livres_demandes=[],
        top_cds_demandes=[],
        top_dvds_demandes=[],
        total_connexions=0,
    )
@application.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("connexion", next=url_for("admin")))
    base = bdd()
    message = None
    erreur = None
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        isbn = request.form.get("isbn_livre", "").strip()
        if not isbn:
            erreur = "ISBN obligatoire."
        elif action == "ajouter":
            nom = request.form.get("nom_livre", "").strip()
            if not nom:
                erreur = "Nom du livre obligatoire."
            else:
                existe = base.execute("SELECT 1 FROM LIVRE WHERE CAST(ISBN_livre AS TEXT)=? LIMIT 1", (isbn,)).fetchone()
                cat = base.execute("SELECT id_categorie FROM CATEGORIE ORDER BY id_categorie LIMIT 1").fetchone()
                if existe:
                    erreur = "Un livre avec cet ISBN existe déjà."
                elif not cat:
                    erreur = "Aucune catégorie trouvée en base."
                else:
                    base.execute(
                        'INSERT INTO LIVRE (nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires) VALUES (?, ?, NULL, NULL, ?, ?, NULL, NULL, 1)',
                        (nom, "Inconnu", int(cat["id_categorie"]), isbn),
                    )
                    base.commit()
                    message = "Livre ajouté."
        elif action == "supprimer":
            livre = base.execute("SELECT 1 FROM LIVRE WHERE CAST(ISBN_livre AS TEXT)=? LIMIT 1", (isbn,)).fetchone()
            if not livre:
                erreur = "Aucun livre trouvé pour cet ISBN."
            else:
                base.execute("UPDATE LIVRE SET total_exemplaires = 0 WHERE CAST(ISBN_livre AS TEXT)=?", (isbn,))
                base.commit()
                message = "Livre marqué comme supprimé."
        else:
            erreur = "Action inconnue."
    livres = base.execute(
        'SELECT nom_livre, CAST(ISBN_livre AS TEXT) AS ISBN_livre FROM LIVRE ORDER BY id_livre DESC LIMIT 30'
    ).fetchall()
    return render_template("admin.html", livres=livres, erreur=erreur, message=message)
@application.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))
if __name__ == "__main__":
    application.run(debug=True)
