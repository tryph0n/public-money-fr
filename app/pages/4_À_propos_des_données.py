import streamlit as st

st.set_page_config(page_title="À propos des données", page_icon=None)

st.title("À propos des données")
st.write(
    "Les données viennent de sources publiques, en accès libre. "
    "Chaque page indiquera ses sources et sa méthode, avec un téléchargement des données "
    "affichées."
)
st.info("Cette page est en construction. Aucune donnée n'est encore publiée.")
