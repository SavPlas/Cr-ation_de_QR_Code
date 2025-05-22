import streamlit as st
import qrcode
from PIL import Image, ImageDraw, ImageFont
import io
import os

# Google API client libraries
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- Configuration des étendues (scopes) pour les APIs Google ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']

# --- Fonction de génération de QR Code avec logo ---
def generate_qr_code_with_logo(url: str, logo_path: str, logo_size_ratio: float = 0.25) -> Image.Image:
    """
    Génère un code QR pour une URL donnée et insère un logo rond au centre.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_width, qr_height = qr_img.size

    if not os.path.exists(logo_path):
        st.error(f"Erreur : Le fichier logo '{logo_path}' est introuvable. "
                 "Veuillez vous assurer qu'il est dans le même répertoire que app.py "
                 "et que le nom est exact.")
        return qr_img

    logo = Image.open(logo_path).convert("RGBA")

    logo_target_width = int(qr_width * logo_size_ratio)
    logo_target_height = int(qr_height * logo_size_ratio)

    logo.thumbnail((logo_target_width, logo_target_height), Image.LANCZOS)

    mask = Image.new('L', logo.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, logo.width, logo.height), fill=255)

    rounded_logo = Image.new('RGBA', logo.size, (0, 0, 0, 0))
    rounded_logo.paste(logo, (0, 0), mask)

    pos = ((qr_width - rounded_logo.width) // 2, (qr_height - rounded_logo.height) // 2)

    qr_img.paste(rounded_logo, pos, rounded_logo)

    return qr_img

# --- Fonctions pour l'intégration Google Docs/Drive API ---

def get_google_service():
    """Authentifie et retourne les services Google Docs et Drive."""
    # Accéder au secret JSON stocké dans Streamlit
    # L'ancienne version utilisait "GOOGLE_CREDENTIALS" comme clé unique.
    # La nouvelle structure est directement les clés du JSON.
    required_keys = ["type", "project_id", "private_key_id", "private_key",
                     "client_email", "client_id", "auth_uri", "token_uri",
                     "auth_provider_x509_cert_url", "client_x509_cert_url",
                     "universe_domain"]

    # Vérifiez si toutes les clés nécessaires sont présentes dans st.secrets
    for key in required_keys:
        if key not in st.secrets:
            st.error(f"Clé manquante dans les secrets Streamlit : '{key}'. "
                     "Veuillez vérifier votre configuration des secrets (Streamlit Cloud ou .streamlit/secrets.toml).")
            st.stop()

    # Construire le dictionnaire des identifiants directement à partir de st.secrets
    credentials_info = {key: st.secrets[key] for key in required_keys}

    try:
        # Utiliser from_service_account_info pour authentifier sans fichier temporaire
        creds = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=SCOPES
        )
    except Exception as e:
        st.error(f"Erreur lors de la création des identifiants Google : {e}")
        st.stop()

    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, drive_service


def create_and_insert_qr_to_doc(docs_service, drive_service, qr_image_buffer: io.BytesIO, page_url_for_doc: str):
    """
    Crée un Google Doc, insère l'image du QR code et la positionne.
    """
    doc_title = f"QR Code pour {page_url_for_doc}"

    try:
        # 1. Uploader l'image du QR code vers Google Drive
        file_metadata = {'name': 'qrcode_image.png', 'mimeType': 'image/png'}
        media = MediaIoBaseUpload(qr_image_buffer, mimetype='image/png', resumable=True)
        uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        image_id = uploaded_file.get('id')
        st.success(f"Image QR code uploadée sur Google Drive : {image_id}")

        # 2. Créer un nouveau Google Doc
        doc_metadata = {'title': doc_title}
        new_doc = docs_service.documents().create(body=doc_metadata).execute()
        document_id = new_doc.get('documentId')
        st.success(f"Document Google Docs créé : {new_doc.get('title')} (ID: {document_id})")

        # 3. Insérer l'image dans le Doc et la formater
        target_size_pt = 141.73

        requests = [
            {
                'insertImage': {
                    'uri': f'https://drive.google.com/uc?id={image_id}',
                    'imageProperties': {
                        'contentUri': f'https://drive.google.com/uc?id={image_id}',
                        'size': {
                            'width': { 'magnitude': target_size_pt, 'unit': 'PT' },
                            'height': { 'magnitude': target_size_pt, 'unit': 'PT' }
                        }
                    },
                    'location': {
                        'segmentId': '',
                        'index': 1
                    }
                }
            },
            {
                'updateParagraphStyle': {
                    'range': {
                        'segmentId': '',
                        'startIndex': 1,
                        'endIndex': 2
                    },
                    'paragraphStyle': {
                        'alignment': 'CENTER'
                    },
                    'fields': 'alignment'
                }
            }
        ]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()
        st.success("Code QR inséré et centré horizontalement dans le document.")

        doc_link = f"https://docs.google.com/document/d/{document_id}/edit"
        st.markdown(f"**Document Google Docs généré :** [Ouvrir le document]({doc_link})")
        st.info("Pour un centrage vertical exact, un ajustement manuel dans Google Docs peut être nécessaire.")

    except Exception as e:
        st.error(f"Une erreur est survenue lors de la création ou de l'insertion dans Google Docs : {e}")


# --- Interface utilisateur Streamlit ---
st.set_page_config(
    page_title="Générateur de QR Code LPETH",
    page_icon="🔗",
    layout="centered",
    initial_sidebar_state="auto"
)

st.title("Générateur de QR Code avec logo LPETH et création Google Docs")
st.markdown("---")

st.write("Bienvenue ! Entrez l'URL de la page pour laquelle vous souhaitez générer un code QR. "
          "Le logo LPETH sera inséré et un nouveau document Google Docs pourra être créé avec le QR code.")

page_url = st.text_input("Veuillez insérer l'URL de la page ici :", "")

LOGO_FILE_NAME = "logo LPETH avril 2016.png"

if page_url:
    st.subheader("Prévisualisation de l'URL :")
    st.code(page_url)

    st.markdown("### Votre Code QR Généré :")

    qr_image_final = generate_qr_code_with_logo(page_url, LOGO_FILE_NAME)

    if qr_image_final:
        st.image(qr_image_final, caption="Code QR avec logo LPETH. Scannez-moi!", use_container_width=False)

        st.markdown("---")
        st.markdown("### Options d'exportation :")

        col1, col2 = st.columns(2)

        with col1:
            # Préparer l'image pour le téléchargement
            download_buffer = io.BytesIO()
            qr_image_final.save(download_buffer, format="PNG")
            download_buffer.seek(0) # IMPORTANT : revenir au début du buffer

            # CORRECTION : Suppression de la ligne label en double
            st.download_button(
                label="Télécharger le Code QR (PNG)", # Cette ligne n'était pas en double
                data=download_buffer, # Passe directement l'objet BytesIO
                file_name="code_qr_lpeth.png",
                mime="image/png"
            )
            st.info("Une fois téléchargé, vous pourrez l'insérer dans Google Docs et ajuster sa taille manuellement.")

        with col2:
            if st.button("Créer un Google Docs avec le QR Code"):
                with st.spinner("Création du Google Docs en cours..."):
                    try:
                        docs_service, drive_service = get_google_service()
                        # Préparer le buffer pour l'upload Google Docs
                        upload_buffer = io.BytesIO()
                        qr_image_final.save(upload_buffer, format="PNG")
                        upload_buffer.seek(0) # Rembobiner le buffer pour l'upload

                        # Passer le buffer à la fonction create_and_insert_qr_to_doc
                        create_and_insert_qr_to_doc(docs_service, drive_service, upload_buffer, page_url)
                    except Exception as e:
                        st.error(f"Échec de l'initialisation des services Google ou de la création du document : {e}")

else:
    st.warning("Veuillez insérer une URL ci-dessus pour générer le code QR.")

st.markdown("---")
st.markdown("Développé avec ❤️ pour LPETH via Streamlit et Google APIs")
