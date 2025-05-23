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

    # Vérifiez si le fichier logo existe. Pour les déploiements Streamlit,
    # le fichier doit être à la racine du dépôt ou dans un sous-dossier spécifié.
    # st.runtime.get_instance() est une astuce pour vérifier l'environnement de déploiement
    # mais os.path.exists est la vérification directe.
    if not os.path.exists(logo_path):
        st.error(f"Erreur : Le fichier logo '{logo_path}' est introuvable. "
                 "Veuillez vous assurer qu'il est dans le même répertoire que app.py "
                 "sur votre dépôt GitHub.")
        # Retourne le QR code sans logo pour éviter de bloquer l'application
        # mais signale le problème.
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

@st.cache_resource
def get_google_service():
    """
    Authentifie et retourne les services Google Docs et Drive.
    Utilise st.cache_resource pour éviter de recréer les services à chaque réexécution.
    Les identifiants sont récupérés depuis st.secrets sous la section 'google_service_account'.
    """
    required_keys = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url",
        "universe_domain"
    ]

    credentials_info = {}
    
    # Vérification que la section 'google_service_account' existe
    if "google_service_account" not in st.secrets:
        st.error("Erreur de configuration des secrets : La section '[google_service_account]' est manquante. "
                 "Veuillez vous assurer que votre fichier secrets.toml sur Streamlit Cloud "
                 "contient cette section et toutes les clés de votre compte de service Google.")
        st.stop() # Arrête l'exécution de l'application si les secrets ne sont pas configurés

    # Récupération des clés sous la section 'google_service_account'
    for key in required_keys:
        if key not in st.secrets["google_service_account"]:
            st.error(f"Erreur de configuration des secrets : La clé '{key}' est manquante "
                     f"dans la section '[google_service_account]'. "
                     "Veuillez vérifier votre fichier secrets.toml sur Streamlit Cloud.")
            st.stop() # Arrête l'exécution si une clé spécifique est manquante
        credentials_info[key] = st.secrets["google_service_account"][key]

    try:
        # La clé privée doit être traitée pour remplacer les '\n' par de vrais retours à la ligne
        # si elle a été stockée en ligne échappée, mais avec les triples guillemets en TOML,
        # elle devrait déjà être correcte. Cependant, une vérification peut être utile.
        # Assurez-vous que la clé privée ne contient pas de guillemets supplémentaires ou d'espaces.
        creds = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=SCOPES
        )
    except Exception as e:
        st.error(f"Erreur lors de la création des identifiants Google. "
                 f"Vérifiez le format de votre clé privée et l'ensemble des informations de votre compte de service. Détail : {e}")
        st.stop() # Arrête l'exécution si l'authentification échoue

    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, drive_service


def create_and_insert_qr_to_doc(docs_service, drive_service, qr_image_buffer: io.BytesIO, page_url_for_doc: str):
    """
    Crée un Google Doc, uploade l'image, la rend publique,
    puis l'insère directement dans le Doc et la centre via l'API Google Docs.
    """
    doc_title = f"QR Code pour {page_url_for_doc}"
    # ADRESSE E-MAIL À PARTAGER AVEC LE DOCUMENT (à remplacer ou obtenir via secrets si elle change)
    YOUR_EMAIL_FOR_DOC_ACCESS = "savery.plasman@eduhainaut.be" # Gardé en dur pour votre cas d'usage spécifique

    try:
        # 1. Uploader l'image du QR code vers Google Drive
        file_metadata = {'name': f'qrcode_{doc_title.replace(" ", "_")}.png', 'mimeType': 'image/png'}
        media = MediaIoBaseUpload(qr_image_buffer, mimetype='image/png', resumable=True)
        uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        image_id = uploaded_file.get('id')
        st.success(f"Image QR code uploadée sur Google Drive : {uploaded_file.get('name')} (ID: {image_id})")

        # Rendre l'image publiquement accessible pour l'API Docs.
        # C'est nécessaire car l'API Docs la récupère via une URL publique.
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        drive_service.permissions().create(fileId=image_id, body=permission, fields='id').execute()
        st.info("Image QR code rendue publiquement accessible sur Google Drive.")

        # 2. Créer un nouveau Google Doc
        doc_metadata = {'title': doc_title}
        new_doc = docs_service.documents().create(body=doc_metadata).execute()
        document_id = new_doc.get('documentId')
        st.success(f"Document Google Docs créé : {new_doc.get('title')} (ID: {document_id})")

        # Partager le document avec l'adresse e-mail spécifiée
        if YOUR_EMAIL_FOR_DOC_ACCESS:
            permission_to_share_with_user = {
                'type': 'user',
                'role': 'writer', # Ou 'reader' si vous voulez seulement lire
                'emailAddress': YOUR_EMAIL_FOR_DOC_ACCESS
            }
            try:
                drive_service.permissions().create(
                    fileId=document_id,
                    body=permission_to_share_with_user,
                    sendNotificationEmail=False # Pour ne pas recevoir un email à chaque création
                ).execute()
                st.info(f"Document partagé avec {YOUR_EMAIL_FOR_DOC_ACCESS}.")
            except Exception as e:
                st.warning(f"Impossible de partager le document avec {YOUR_EMAIL_FOR_DOC_ACCESS}. "
                           f"Vérifiez que votre compte de service a la permission de partager des fichiers Drive. Erreur: {e}")

        # 3. Insérer l'image et la centrer directement via l'API Docs
        st.info("Insertion de l'image dans le document Google Docs...")

        requests_body = [
            {
                'insertInlineImage': {
                    'uri': f'https://drive.google.com/uc?id={image_id}',
                    'location': {
                        'segmentId': '',
                        'index': 1 # Insère l'image au début du document
                    },
                    'objectSize': {
                        'width': {
                            'magnitude': 300,
                            'unit': 'PT'
                        },
                        'height': {
                            'magnitude': 300,
                            'unit': 'PT'
                        }
                    }
                }
            },
            {
                'updateParagraphStyle': {
                    'range': {
                        'segmentId': '',
                        'startIndex': 1, # Applique le style au paragraphe contenant l'image
                        'endIndex': 2
                    },
                    'paragraphStyle': {
                        'alignment': 'CENTER'
                    },
                    'fields': 'alignment'
                }
            }
        ]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests_body}).execute()
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

# Le nom du fichier logo. Assurez-vous que ce fichier est présent dans votre dépôt GitHub à la racine.
LOGO_FILE_NAME = "image_74db4d.png" 

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

            st.download_button(
                label="Télécharger le Code QR (PNG)",
                data=download_buffer,
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
