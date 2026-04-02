from datetime import date


def date_francaise(valeur_date):
    return valeur_date.strftime("%d/%m/%Y")


def faire_slug(texte):
    return "-".join(str(texte).strip().lower().split())


def aujourdhui_fr():
    return date_francaise(date.today())
