# rajouter les imports
def date_francaise(valeur_date):
    return valeur_date.strftime("%d/%m/%Y")



"""def prochain_nom_image(base,type): # type cest pr cddvd ou livre
    total = base.execute('SELECT COUNT(*) AS total FROM "CD/DVD"').fetchone()["total"]
    return "cddvd_%02d.jpg" % (int(total) + 1)"""

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
"""def supespace(texte):
    texte_ascii = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode("ascii")
    return "-".join(texte_ascii.lower().strip().split())"""
def categories_menu():
    base = bdd()
    lignes = base.execute("SELECT id_categorie, nom_categorie FROM CATEGORIE ORDER BY id_categorie").fetchall()
    return [{"id": ligne["id_categorie"], "nom": ligne["nom_categorie"], "slug": supespace(ligne["nom_categorie"])} for ligne in lignes]
def prochain_identifiant(base, table, colonne): #donne lid suivant
    return int(
        base.execute(
            'SELECT COALESCE(MAX(CAST("' + colonne + '" AS INTEGER)), 0) + 1 AS prochain FROM "' + table + '"'
        ).fetchone()["prochain"]
    )
def ajouter_log_connexion(id_client): #pour le grpahique
    base = bdd()
    assurer_tables_stats_connexion(base)
    instant = datetime.now()
    base.execute(
        "INSERT INTO CONNEXION_LOG (id_client, date_connexion) VALUES (?, ?)",
        (id_client, instant.strftime("%Y-%m-%d %H:%M:%S")),
    )
    incrementer_stats_connexion(base, instant)
    base.commit()
def incrementer_stats_connexion(base, instant=None):
    moment = instant or datetime.now()
    heure = int(moment.strftime("%H"))
    # UPSERT SQLite: crée la ligne horaire si absente, sinon incrémente directement.
    base.execute( #encore pr le graphique
        """
        INSERT INTO CONNEXION_STATS_HEURE (heure, nb_connexions)
        VALUES (?, 1)
        ON CONFLICT(heure) DO UPDATE SET nb_connexions = nb_connexions + 1
        """,
        (heure,),
    )
    base.execute( # grp
        """
        UPDATE CONNEXION_STATS_GLOBALE
        SET total_connexions = total_connexions + 1
        WHERE id_unique = 1
        """,
    )
def assurer_tables_stats_connexion(base):#grph
    # Tables de stats indépendantes de CONNEXION_LOG pour un accès rapide au graphe.
    base.execute(
        """
        CREATE TABLE IF NOT EXISTS CONNEXION_STATS_HEURE (
            heure INTEGER PRIMARY KEY,
            nb_connexions INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    base.execute(
        """
        CREATE TABLE IF NOT EXISTS CONNEXION_STATS_GLOBALE (
            id_unique INTEGER PRIMARY KEY CHECK (id_unique = 1),
            total_connexions INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    base.execute(
        "INSERT OR IGNORE INTO CONNEXION_STATS_GLOBALE (id_unique, total_connexions) VALUES (1, 0)"
    )
    lignes_stats = base.execute("SELECT COUNT(*) AS total FROM CONNEXION_STATS_HEURE").fetchone()["total"]
    if int(lignes_stats) == 0:
        for h in range(24):
            base.execute(
                "INSERT OR IGNORE INTO CONNEXION_STATS_HEURE (heure, nb_connexions) VALUES (?, 0)",
                (h,),
            )
    total_global = int(
        base.execute(
            "SELECT total_connexions FROM CONNEXION_STATS_GLOBALE WHERE id_unique = 1"
        ).fetchone()["total_connexions"]
    )
    if total_global == 0:
        # Migration douce: si les stats sont vides, on reconstruit à partir de l'historique brut.
        agregats = base.execute(
            "SELECT CAST(strftime('%H', date_connexion) AS INTEGER) AS heure, COUNT(*) AS total FROM CONNEXION_LOG GROUP BY heure"
        ).fetchall()
        somme = 0
        for ligne in agregats:
            if ligne["heure"] is None:
                continue
            somme += int(ligne["total"])
            base.execute(
                "UPDATE CONNEXION_STATS_HEURE SET nb_connexions = ? WHERE heure = ?",
                (int(ligne["total"]), int(ligne["heure"])),
            )
        base.execute(
            "UPDATE CONNEXION_STATS_GLOBALE SET total_connexions = ? WHERE id_unique = 1",
            (somme,),
        )
    base.commit()
    # terminé le graph
def verifier_connexion(): #pr pas qua chaque page on doit se reconnecter
    if "utilisateur" not in session:
        return redirect(url_for("connexion", next=request.path))
    return None
@application.context_processor
def cookie(): # viens mettre de sinfos ds le cookie
    return {
        "utilisateur": session.get("utilisateur"),
        "admin_connecte": bool(session.get("admin")), # admin oui ou non 0 ou 1  (le mettre aussi ds la table)
        "menu_categories": categories_menu(),
    }
def assurer_colonne_total_exemplaires_livre(base):
    colonnes = [ligne["name"] for ligne in base.execute("PRAGMA table_info('LIVRE')").fetchall()]
    if "total_exemplaires" not in colonnes:
        base.execute("ALTER TABLE LIVRE ADD COLUMN total_exemplaires INTEGER")
        base.execute("UPDATE LIVRE SET total_exemplaires = 1 WHERE total_exemplaires IS NULL")
    base.execute("UPDATE LIVRE SET total_exemplaires = 1 WHERE total_exemplaires IS NULL OR total_exemplaires < 1")
    base.execute("UPDATE LIVRE SET total_exemplaires = 5 WHERE total_exemplaires > 5")
    base.commit()
def assurer_colonne_image_cddvd(base):
    colonnes = [ligne["name"] for ligne in base.execute('PRAGMA table_info("CD/DVD")').fetchall()]
    if "image" not in colonnes:
        base.execute('ALTER TABLE "CD/DVD" ADD COLUMN image TEXT')
        base.commit()
def assurer_colonne_total_exemplaires_cddvd(base):
    colonnes = [ligne["name"] for ligne in base.execute('PRAGMA table_info("CD/DVD")').fetchall()]
    if "total_exemplaires" not in colonnes:
        base.execute('ALTER TABLE "CD/DVD" ADD COLUMN total_exemplaires INTEGER')
    lignes = base.execute('SELECT "id_CD/DVD" AS id_cd_dvd, "nom_CD/DVD" AS nom_cd_dvd, total_exemplaires FROM "CD/DVD"').fetchall()
    modifie = False
    for ligne in lignes:
        total = ligne["total_exemplaires"]
        if total is None or int(total) < 1:
            base.execute(
                'UPDATE "CD/DVD" SET total_exemplaires = ? WHERE "id_CD/DVD" = ?',
                (stock_initial_cddvd(ligne["nom_cd_dvd"]), ligne["id_cd_dvd"]),
            )
            modifie = True
        elif int(total) > 5:
            base.execute(
                'UPDATE "CD/DVD" SET total_exemplaires = 5 WHERE "id_CD/DVD" = ?',
                (ligne["id_cd_dvd"],),
            )
            modifie = True
    if modifie or "total_exemplaires" not in colonnes:
        base.commit()
   def restaurer_depuis_suppression(suppression):
        try:
            payload = json.loads(suppression["payload_json"])
        except json.JSONDecodeError:
            return None, "Historique invalide, restauration impossible."
        if not payload:
            return None, "Historique invalide, restauration impossible."
        if payload.get("mode") == "retrait_exemplaire":
            # Cas 1: restauration d'un retrait de stock (on remonte juste `total_exemplaires`).
            try:
                if suppression["type_media"] == "livre":
                    isbn = str(suppression["reference_media"])
                    livre = base.execute(
                        """
                        SELECT id_livre, nom_livre, COALESCE(total_exemplaires, 1) AS total_exemplaires
                        FROM LIVRE
                        WHERE CAST(ISBN_livre AS TEXT) = ?
                        ORDER BY id_livre
                        LIMIT 1
                        """,
                        (isbn,),
                    ).fetchone()
                    if not livre:
                        return None, "Restauration impossible : livre introuvable."
                    if int(livre["total_exemplaires"] or 1) >= 5:
                        return None, "Stock maximum atteint (5 exemplaires) pour ce livre."
                    base.execute(
                        """
                        UPDATE LIVRE
                        SET total_exemplaires = COALESCE(total_exemplaires, 1) + 1
                        WHERE CAST(ISBN_livre AS TEXT) = ?
                        """,
                        (isbn,),
                    )
                    message_local = "Exemplaire restauré pour le livre : " + str(livre["nom_livre"])
                else:
                    numero = str(suppression["reference_media"])
                    cddvd = base.execute(
                        """
                        SELECT "id_CD/DVD" AS id_cd_dvd, "nom_CD/DVD" AS nom_cd_dvd, COALESCE(total_exemplaires, 1) AS total_exemplaires
                        FROM "CD/DVD"
                        WHERE "id_CD/DVD" = ?
                        """,
                        (numero,),
                    ).fetchone()
                    if not cddvd:
                        return None, "Restauration impossible : CD/DVD introuvable."
                    if int(cddvd["total_exemplaires"] or 1) >= 5:
                        return None, "Stock maximum atteint (5 exemplaires) pour ce CD/DVD."
                    base.execute(
                        """
                        UPDATE "CD/DVD"
                        SET total_exemplaires = COALESCE(total_exemplaires, 1) + 1
                        WHERE "id_CD/DVD" = ?
                        """,
                        (numero,),
                    )
                    message_local = "Exemplaire restauré pour le CD/DVD : " + str(cddvd["nom_cd_dvd"])
                base.execute(
                    """
                    UPDATE SUPPRESSION_LOG
                    SET restaure = 1, date_restauration = ?
                    WHERE id_suppression = ?
                    """,
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suppression["id_suppression"]),
                )
                base.commit()
                return message_local, None
            except Exception as e:
                return None, "Restauration impossible : " + str(e)
        try:
            # Cas 2: restauration d'une suppression complète (réinsertion de la ligne supprimée).
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
                message_local = "Livre restauré."
            else:
                try:
                    base.execute(
                        """
                        INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image, total_exemplaires)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload.get("id_cd_dvd"),
                            payload.get("nom_cd_dvd"),
                            payload.get("annee_cd_dvd"),
                            payload.get("artiste_cd_dvd"),
                            payload.get("image"),
                            int(payload.get("total_exemplaires") or stock_initial_cddvd(payload.get("nom_cd_dvd"))),
                        ),
                    )
                except sqlite3.IntegrityError:
                    prochain_numero = base.execute(
                        'SELECT COALESCE(MAX(CAST("id_CD/DVD" AS INTEGER)), 0) + 1 AS prochain FROM "CD/DVD"'
                    ).fetchone()["prochain"]
                    base.execute(
                        """
                        INSERT INTO "CD/DVD" ("id_CD/DVD", "nom_CD/DVD", "annee_CD/DVD", "artiste_CD/DVD", image, total_exemplaires)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(prochain_numero),
                            payload.get("nom_cd_dvd"),
                            payload.get("annee_cd_dvd"),
                            payload.get("artiste_cd_dvd"),
                            payload.get("image"),
                            int(payload.get("total_exemplaires") or stock_initial_cddvd(payload.get("nom_cd_dvd"))),
                        ),
                    )
                message_local = "CD/DVD restauré."
            base.execute(
                """
                UPDATE SUPPRESSION_LOG
                SET restaure = 1, date_restauration = ?
                WHERE id_suppression = ?
                """,
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), suppression["id_suppression"]),
            )
            base.commit()
            return message_local, None
        except Exception as e:
            return None, "Restauration impossible : " + str(e)


