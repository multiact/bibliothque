from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("principal.html")

@app.route("/catalogue/<categorie>")
def catalogue(categorie):
    return f"Catalogue : {categorie}"

@app.route("/reserver", methods=["GET", "POST"])
def reserver():
    if request.method == "POST":
        carte = request.form["carte"]
        titre = request.form["titre"]
        auteur = request.form["auteur"]
        date = request.form["date_reservation"]
        bibliotheque = request.form["bibliotheque"]

        print("Réservation :", carte, titre, auteur, date, bibliotheque)

    return render_template("reserver.html")

@app.route("/rendre", methods=["GET", "POST"])
def rendre():
    if request.method == "POST":
        carte = request.form["carte"]
        titre = request.form["titre"]
        auteur = request.form["auteur"]
        date = request.form["date_retour"]

        print("Retour :", carte, titre, auteur, date)

    return render_template("rendre.html")

@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        print("Connexion :", email, password)
        return redirect(url_for("home"))

    return render_template("connexion.html")

@app.route("/creer_compte", methods=["GET", "POST"])
def creer_compte():
    if request.method == "POST":
        prenom = request.form["prenom"]
        nom_utilisateur = request.form["nom_utilisateur"]
        date_naissance = request.form["date_naissance"]
        code_postal = request.form["code_postal"]
        email = request.form["email"]
        password = request.form["password"]

        print("Nouveau compte :", prenom, nom_utilisateur, email)
        return redirect(url_for("connexion"))

    return render_template("connexion.html")
@app.route("/romans")
def romans():
    return render_template("romans.html")

if __name__ == "__main__":

    app.run(debug=True)
