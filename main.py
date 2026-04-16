from datetime import date, datetime, timedelta
from collections import Counter
from io import BytesIO
import base64
import sqlite3
from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from fonctions import bdd, fermer_bdd, contexte_global, faire_slug, date_francaise, verifier_connexion
try:
    from matplotlib.figure import Figure
except ImportError:
    Figure = None

application = Flask(__name__)
application.secret_key = "cle_secrete_bibliotheque"

@application.teardown_appcontext
def nettoyage_bdd(_erreur):
    fermer_bdd(_erreur)

@application.context_processor
def injecter_contexte():
    return contexte_global()


@application.route("/")
def accueil():
    nom = session.get("utilisateur", {}).get("prenom", "")
    return render_template("principal.html", nomutlisateur=nom)
@application.route("/catalogue/<categorie_url>")
def catalogue(categorie_url):
    base = bdd()
    recherche = request.args.get("q", "").strip().lower()
    # On récupère toutes les catégories depuis la base.
    toutes_categories = base.execute(
        "SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie"
    ).fetchall()

    categorie_trouvee = None
    for c in toutes_categories:
        if faire_slug(c["nom_categorie"]) == categorie_url:
            categorie_trouvee = c
            break

    if categorie_trouvee is None:
        return redirect(url_for("accueil"))
    livres = [
        dict(x)
        for x in base.execute(
            """
            SELECT
                id_livre,
                nom_livre,
                auteur_livre,
                ISBN_livre,
                resume,
                image,
                total_exemplaires,
                disponibilité
            FROM LIVRE
            WHERE id_categorie = ?
            ORDER BY nom_livre
            """,
            (categorie_trouvee["id_categorie"],),
        ).fetchall()
    ]
    if recherche:
        livres = [
            l for l in livres
            if recherche in str(l.get("nom_livre", "")).lower()
            or recherche in str(l.get("auteur_livre", "")).lower()
            or recherche in str(l.get("ISBN_livre", "")).lower()
        ]
    # On prépare les données pour l'affichage HTML.
    for livre in livres:
        livre["ISBN_livre"] = str(livre.get("ISBN_livre") or "")
        livre["total_exemplaires"] = int(livre.get("total_exemplaires") or 1)
        livre["exemplaires_restants"] = int(livre.get("disponibilité") or 0)
        livre["disponible"] = 1 if livre["exemplaires_restants"] > 0 else 0
    return render_template(
        "catalogue.html",
        categorie={
            "id": categorie_trouvee["id_categorie"],
            "nom": categorie_trouvee["nom_categorie"],
            "categorie_url": categorie_url,
        },
        livres=livres,
        recherche=recherche,
    )
@application.route("/cddvd")
def cddvd():
    base = bdd()
    recherche = request.args.get("q", "").strip().lower()
    cddvds = [
        dict(x)
        for x in base.execute(
            """
            SELECT
                cddvd.id_cd_dvd,
                cddvd.nom_cd_dvd,
                cddvd.annee_cd_dvd,
                cddvd.artiste_cd_dvd,
                cddvd.image,
                cddvd.total_exemplaires
            FROM cddvd
            ORDER BY cddvd.nom_cd_dvd
            """,
        ).fetchall()
    ]
    if recherche:
        cddvds = [
            c for c in cddvds
            if recherche in str(c.get("nom_cd_dvd", "")).lower()
            or recherche in str(c.get("artiste_cd_dvd", "")).lower()
            or recherche in str(c.get("id_cd_dvd", "")).lower()
        ]
    for item in cddvds:
        item["total_exemplaires"] = int(item.get("total_exemplaires") or 1)
        item["exemplaires_restants"] = int(item["total_exemplaires"])
    return render_template("cddvd.html", cddvds=cddvds, recherche=recherche)
@application.route("/reserver", methods=["GET", "POST"])
def reserver():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    base = bdd()
    message = None
    erreur = None
    utilisateur_id = session["utilisateur"]["id"]
    def creer_resa():
        auj = date.today()
        curseur = base.execute(
            "INSERT INTO RESERVATION (date_reservation, date_de_retour, id_client, date_limite_retour, date_retour_effective) VALUES (?, NULL, ?, ?, NULL)",
            (date_francaise(auj), utilisateur_id, date_francaise(auj + timedelta(days=21))),
        )
        return curseur.lastrowid
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        elif isbn:
            livre = base.execute(
                'SELECT id_livre, nom_livre, disponibilité FROM LIVRE WHERE ISBN_livre=? ORDER BY id_livre LIMIT 1',
                (isbn,),
            ).fetchone()
            
            if not livre:
                erreur = "Livre introuvable pour cet ISBN."
            elif int(livre["disponibilité"] or 0) <= 0:
                # L'ardoise est à 0, on bloque la réservation !
                erreur = "Ce livre est actuellement indisponible."
            else:
                reservation_id = creer_resa()
                base.execute(
                    "INSERT INTO ligne_livre (id_livre, id_reservation) VALUES (?, ?)",                    
                    (livre["id_livre"], reservation_id),
                )
                base.execute(
                    'UPDATE LIVRE SET disponibilité = disponibilité - 1 WHERE id_livre=?',
                    (livre["id_livre"],)
                )
                base.commit()
                message = "Réservation enregistrée pour le livre : " + str(livre["nom_livre"])
        else:
            cd = base.execute(
                "SELECT id_cd_dvd, nom_cd_dvd FROM cddvd WHERE id_cd_dvd=?",
                (numero,),
            ).fetchone()
            
            if not cd:
                erreur = "CD/DVD introuvable pour ce numéro."
            else:
                reservation_id = creer_resa()
                base.execute(
                    "INSERT INTO ligne_cddvd (id_cd_dvd, id_reservation, date_de_retour) VALUES (?, ?, NULL)",
                    (cd["id_cd_dvd"], reservation_id),
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
        (utilisateur_id,),
    ).fetchall()
    return render_template("reserver.html", message=message, erreur=erreur, historique=historique)
@application.route("/mes_reservations")
def mes_reservations():
    redirection = verifier_connexion()
    if redirection:
        return redirection
    reservations = bdd().execute(
        """
        SELECT type_media, id_reservation, nom_media, auteur_media, reference_media, date_reservation, date_limite_retour, date_retour_effective
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
    utilisateur_id = session["utilisateur"]["id"]
    if request.method == "POST":
        isbn = request.form.get("isbn", "").strip()
        numero = request.form.get("numero_cd_dvd", "").strip()
        if not isbn and not numero:
            erreur = "Entre un ISBN livre ou un numéro CD/DVD."
        elif isbn and numero:
            erreur = "Remplis un seul champ : ISBN livre ou numéro CD/DVD."
        elif isbn:
            resa = base.execute(
                "SELECT r.id_reservation, l.id_livre, l.nom_livre FROM RESERVATION r JOIN ligne_livre ll ON ll.id_reservation=r.id_reservation JOIN LIVRE l ON l.id_livre=ll.id_livre WHERE r.id_client=? AND l.ISBN_livre=? AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1",
                (utilisateur_id, isbn),
            ).fetchone()
            
            if not resa:
                erreur = "Aucune réservation active pour cet ISBN."
            else:
                base.execute(
                    "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                    (date_francaise(date.today()), date_francaise(date.today()), resa["id_reservation"]),
                )
                base.execute(
                    'UPDATE LIVRE SET disponibilité = disponibilité + 1 WHERE id_livre=?',
                    (resa["id_livre"],)
                )
                base.commit()
                message = "Retour enregistré pour le livre : " + str(resa["nom_livre"])
        else:
            resa = base.execute(
                "SELECT r.id_reservation, cddvd.id_cd_dvd, cddvd.nom_cd_dvd FROM RESERVATION r JOIN ligne_cddvd ON ligne_cddvd.id_reservation = r.id_reservation JOIN cddvd ON cddvd.id_cd_dvd = ligne_cddvd.id_cd_dvd WHERE r.id_client=? AND ligne_cddvd.id_cd_dvd=? AND r.date_retour_effective IS NULL ORDER BY r.id_reservation DESC LIMIT 1",
                (utilisateur_id, numero),
            ).fetchone()
            if not resa:
                erreur = "Aucune réservation pour ce numéro CD/DVD."
            else:
                base.execute(
                    "UPDATE RESERVATION SET date_retour_effective=?, date_de_retour=? WHERE id_reservation=?",
                    (date_francaise(date.today()), date_francaise(date.today()), resa["id_reservation"]),
                )
                base.execute(
                    "UPDATE ligne_cddvd SET date_de_retour=? WHERE id_reservation=?",
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
                session["admin"] = True  # On ajoute le macaron Admin sur son badge
                return redirect(url_for("admin"))
            else:
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
        mdp_hash = generate_password_hash(mot_de_passe)
        
        curseur = base.execute(
            'INSERT INTO CLIENT (nom_client, prenom_client, adressepostale_client, adressemail_client, date_naissance_client, telephone_client, nom_utilisateur, mot_de_passe, date_creation, code_postal, est_admin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)',
            (nom_utilisateur, prenom, code_postal, email, date_naissance, None, nom_utilisateur, mdp_hash, date_francaise(date.today()), code_postal),
        )
        cid = curseur.lastrowid
        base.commit()
    except sqlite3.IntegrityError:
        return render_template("connexion.html", erreur="Cet e-mail ou ce nom d'utilisateur existe déjà.", prochain=prochain)
    session["utilisateur"] = {"id": cid, "prenom": prenom, "nom_utilisateur": nom_utilisateur, "email": email}
    
    session.pop("admin", None)
    
    return redirect(prochain)


@application.route("/autres")
@application.route("/statistiques")
def autres():
    base = bdd()
    nb_clients = int(base.execute("SELECT COUNT(*) FROM CLIENT").fetchone()[0])
    nb_reservations_actives = int(
        base.execute("SELECT COUNT(*) FROM RESERVATION WHERE date_retour_effective IS NULL").fetchone()[0]
    )
    top_livres_demandes = [
        dict(x)
        for x in base.execute(
            f"""
            SELECT
                l.id_livre,
                l.nom_livre,
                c.nom_categorie,
                COUNT(*) AS nb_demandes
            FROM LIGNE_LIVRE ll
            JOIN LIVRE l ON l.id_livre = ll.id_livre
            LEFT JOIN CATEGORIE c ON c.id_categorie = l.id_categorie
            GROUP BY l.id_livre, l.nom_livre, c.nom_categorie
            ORDER BY nb_demandes DESC, l.nom_livre ASC
            LIMIT 10
            """
        ).fetchall()
    ]
    for livre in top_livres_demandes:
        livre["slug_categorie"] = faire_slug(livre.get("nom_categorie") or "")

    total_reservations_30j = 0
    aujourd_hui = date.today()
    date_min = aujourd_hui - timedelta(days=29)
    reservations = base.execute(
        "SELECT date_reservation FROM RESERVATION WHERE date_reservation IS NOT NULL"
    ).fetchall()

    compte_par_jour = Counter()
    for ligne in reservations:
        date_brute = str(ligne["date_reservation"] or "").strip()
        if not date_brute:
            continue
        try:
            jour = datetime.strptime(date_brute, "%d/%m/%Y").date()
        except ValueError:
            continue
        if date_min <= jour <= aujourd_hui:
            compte_par_jour[jour] += 1

    stats_30j = []
    for i in range(30):
        jour = date_min + timedelta(days=i)
        nb = int(compte_par_jour.get(jour, 0))
        total_reservations_30j += nb
        stats_30j.append({"date": jour.strftime("%d/%m"), "nb_reservations": nb})

    stats_chart_image = ""
    stats_chart_error = ""
    if Figure is None:
        stats_chart_error = "Graphique indisponible sur cet environnement (matplotlib absent)."
    else:
        try:
            figure = Figure(figsize=(8.2, 3.1))
            axe = figure.add_subplot(111)
            labels = [x["date"] for x in stats_30j]
            valeurs = [x["nb_reservations"] for x in stats_30j]
            x = list(range(len(labels)))
            axe.plot(x, valeurs, marker="o", linewidth=2, markersize=4, color="#1f77b4")
            axe.set_title("Nombre total de réservations par jour (30 derniers jours)")
            axe.set_ylabel("Nombre de réservations")
            axe.set_xticks(x[::5], [labels[i] for i in x[::5]])
            axe.grid(axis="y", alpha=0.3)
            tampon = BytesIO()
            figure.tight_layout()
            figure.savefig(tampon, format="png")
            stats_chart_image = base64.b64encode(tampon.getvalue()).decode("utf-8")
        except Exception:
            stats_chart_error = "Graphique indisponible sur cet environnement."
    return render_template(
        "autres.html",
        nb_clients=nb_clients,
        nb_reservations_actives=nb_reservations_actives,
        total_reservations_30j=total_reservations_30j,
        stats_chart_image=stats_chart_image,
        stats_chart_error=stats_chart_error,
        top_livres_demandes=top_livres_demandes,
    )
@application.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("connexion", next=url_for("admin")))
    
    base = bdd()
    message = None
    erreur = None
    
    categories = [dict(x) for x in base.execute(
        "SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY nom_categorie"
    ).fetchall()]
    
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        isbn = request.form.get("isbn_livre", "").strip()
        
        if not isbn:
            erreur = "L'ISBN est obligatoire."
        elif action == "ajouter":
            nom = request.form.get("nom_livre", "").strip()
            auteur = request.form.get("auteur_livre", "").strip()
            resume = request.form.get("resume_livre", "").strip()
            categorie_choisie = request.form.get("id_categorie", "").strip()
            existe = base.execute(
                "SELECT nom_livre FROM LIVRE WHERE ISBN_livre=? LIMIT 1",
                (isbn,),
            ).fetchone()
            if existe:
                base.execute(
                    "UPDATE LIVRE SET total_exemplaires = COALESCE(total_exemplaires, 0) + 1, disponibilité = COALESCE(disponibilité, 0) + 1 WHERE ISBN_livre=?",
                    (isbn,),
                )
                base.commit()
                message = f"Exemplaire ajouté pour '{existe['nom_livre']}' (ISBN {isbn})."
            elif not nom:
                erreur = "Le nom du livre est obligatoire pour un nouveau livre."
            elif not categorie_choisie:
                erreur = "Veuillez choisir une catégorie pour un nouveau livre."
            else:
                base.execute(
                    "INSERT INTO LIVRE (nom_livre, auteur_livre, maison_edition_livre, annee_livre, id_categorie, ISBN_livre, resume, image, total_exemplaires, disponibilité) VALUES (?, ?, NULL, NULL, ?, ?, ?, NULL, 1, 1)",
                    (nom, auteur or "Inconnu", int(categorie_choisie), isbn, resume or None),
                )
                base.commit()
                message = f"Le livre '{nom}' a été ajouté avec succès."
                    
        elif action == "supprimer":
            livre = base.execute("SELECT nom_livre FROM LIVRE WHERE ISBN_livre=? LIMIT 1", (isbn,)).fetchone()
            if not livre:
                erreur = "Aucun livre trouvé pour cet ISBN."
            else:
                base.execute("DELETE FROM LIVRE WHERE ISBN_livre=?", (isbn,))
                base.commit()
                message = f"Le livre '{livre['nom_livre']}' a été définitivement retiré."
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
