import streamlit as st

st.set_page_config(page_title="Argent public", page_icon=None)

st.title("Argent public de la France")
st.write(
    "Trois projets de données ouvertes sur l'argent public. "
    "Chacun répond à une question. L'application est en construction : "
    "les pages des projets sont encore vides."
)

st.info(
    "Cette application est hébergée sur une offre gratuite. Après 15 minutes sans visite, "
    "elle se met en veille. Le premier chargement peut alors durer environ une minute. "
    "Patientez : la page s'affiche ensuite normalement."
)

st.header("Finances publiques")
st.write(
    "Les gouvernements successifs font-ils ce qu'ils annoncent ? "
    "Ce qu'ils votent, puis ce qu'ils exécutent, est-il cohérent avec l'état des finances "
    "de l'État à ce moment-là ?"
)

st.header("Sécurité")
st.write(
    "L'État tient-il ses propres engagements sur les moyens de la sécurité ? "
    "Qu'est-ce qui permet de montrer une baisse de l'insécurité ?"
)

st.header("Élection 2027")
st.write(
    "Les chiffres avancés par les candidats sont-ils cohérents avec les comptes réels "
    "de la France ?"
)

st.caption("Voir aussi la page « À propos des données ».")
