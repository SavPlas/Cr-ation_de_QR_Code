import streamlit as st
import qrcode
from PIL import Image, ImageDraw, ImageFont # Pillow est nécessaire pour la manipulation d'images
import io # Pour gérer les flux de données (téléchargement d'image)
import os # Pour vérifier l'existence du fichier logo

# Google API client libraries
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- Configuration des étendues (scopes) pour les APIs Google ---
# 'drive.file' limite l'accès aux fichiers créés ou ouverts par l'application. Plus sûr que 'drive'.
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']

# --- Fonction de génération de QR Code avec logo ---
def generate_qr_code_with_logo(url: str, logo_path: str, logo_size_ratio: float = 0.25) -> Image.Image:
    """
    Génère un code QR pour une URL donnée et insère un logo rond au centre.

    Args:
        url (str): L'URL à encoder dans le code QR.
        logo_path (str): Le chemin d'accès au fichier image du logo (ex: "logo LPETH avril 2016.png").
        logo_size_ratio (float): La proportion de la taille du logo par rapport au code QR total.
                                 Par exemple, 0.25 signifie que le logo aura une largeur/hauteur égale à 25% du QR.

    Returns:
        PIL.Image.Image: L'objet image du code QR avec le logo inséré.
    """

    # 1. Créer l'objet QR Code
    qr = qrcode.QRCode(
        version=1, # Version 1 est la plus petite. Ajustez si l'URL est très longue.
        error_correction=qrcode.constants.ERROR_CORRECT_H, # Niveau de correction d'erreur "H" (30%)
                                                           # Indispensable pour insérer un logo au centre.
        box_size=10, # Taille de chaque "boîte" (pixel) du QR. Plus grand = image plus grande.
        border=4,    # Nombre de "boîtes" de bordure blanches autour du QR.
    )
    qr.add_data(url)
    qr.make(fit=True)

    # 2. Générer l'image de base du QR Code
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_width, qr_height = qr_img.size

    # 3. Charger et préparer le logo
    if not os.path.exists(logo_path):
        st.error(f"Erreur : Le fichier logo '{logo_path}' est introuvable. "
                 "Veuillez vous assurer qu'il est dans le même répertoire que app.py "
                 "et que le nom est exact.")
        return qr_img # Retourne le QR code sans logo si le logo n'est pas trouvé

    logo = Image.open(logo_path).convert("RGBA") # Charger en RGBA pour gérer la transparence

    # 4. Calculer la taille cible du logo et le redimensionner
    logo_target_width = int(qr_width * logo_size_ratio)
    logo_target_height = int(qr_height * logo_size_ratio)

    # Redimensionner le logo en conservant ses proportions
    # Utilisez LANCZOS pour une meilleure qualité de redimensionnement
    logo.thumbnail((logo_target_width, logo_target_height), Image.LANCZOS)

    # 5. Créer un masque rond pour le logo
    # Un masque en mode 'L' (luminance) où le blanc (255) est opaque et le noir (0) est transparent
    mask = Image.new('L', logo.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    # Dessine un cercle blanc rempli (255) sur le masque noir, créant la forme ronde
    draw_mask.ellipse((0, 0, logo.width, logo.height), fill=255)

    # Appliquer le masque rond au logo
    # Créer une nouvelle image RGBA entièrement transparente pour le logo arrondi
    rounded_logo = Image.new('RGBA', logo.size, (0, 0, 0, 0))
    # Coller le logo original sur cette image transparente en utilisant le masque
    rounded_logo.paste(logo, (0, 0), mask)

    # 6. Calculer la position pour centrer le logo sur le QR code
    pos = ((qr_width - rounded_logo.width) // 2, (qr_height - rounded_logo.height) // 2)

    # 7. Coller le logo arrondi et masqué sur l'image du QR code
    # Le troisième argument 'rounded_logo' est utilisé comme masque pour paste,
    # assurant que les parties transparentes du logo ne recouvrent pas le QR code.
    qr_img.paste(rounded_logo, pos, rounded_logo)

    return qr_img

# --- Fonctions pour l'intégration Google Docs/Drive API ---

def get_google_service():
    """Authentifie et retourne les services Google Docs et Drive."""
    # Accéder au secret JSON stocké dans Streamlit
    if "GOOGLE_CREDENTIALS" not in st.secrets:
        st.error("Les identifiants Google Cloud ne sont pas configurés dans les secrets Streamlit.")
        st.stop() # Arrête l'exécution de l'application

    # Écrire le secret JSON dans un fichier temporaire pour l'authentification
    # C'est nécessaire car google-auth-library attend un chemin de fichier
    creds_file_content = st.secrets["GOOGLE_CREDENTIALS"]
    creds_path = "google_credentials.json" # Nom temporaire pour le fichier de crédentiels
    try:
        with open(creds_path, "w") as f:
            f.write(creds_file_content)

        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    finally:
        # Nettoyer le fichier temporaire (important pour la sécurité)
        if os.path.exists(creds_path):
            os.remove(creds_path)

    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, drive_service

def create_and_insert_qr_to_doc(docs_service, drive_service, qr_image_bytes, page_url_for_doc: str):
    """
    Crée un Google Doc, insère l'image du QR code et la positionne.
    """
    doc_title = f"QR Code pour {page_url_for_doc}"

    try:
        # 1. Uploader l'image du QR code vers Google Drive
        file_metadata = {'name': 'qrcode_image.png', 'mimeType': 'image/png'}
        media = MediaIoBaseUpload(io.BytesIO(qr_image_bytes), mimetype='image/png', resumable=True)
        uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        image_id = uploaded_file.get('id')
        st.success(f"Image QR code uploadée sur Google Drive : {image_id}")

        # 2. Créer un nouveau Google Doc
        doc_metadata = {'title': doc_title}
        new_doc = docs_service.documents().create(body=doc_metadata).execute()
        document_id = new_doc.get('documentId')
        st.success(f"Document Google Docs créé : {new_doc.get('title')} (ID: {document_id})")

        # 3. Insérer l'image dans le Doc et la formater
        # Les dimensions en points (PT): 1 pouce = 72 points. 50mm = 5cm = ~1.9685 pouces = 141.73 points
        target_size_pt = 141.73

        requests = [
            # Insérer l'image au début du document
            {
                'insertImage': {
                    'uri': f'https://drive.google.com/uc?id={image_id}', # Lien public de l'image sur Drive
                    'imageProperties': {
                        'contentUri': f'https://drive.google.com/uc?id={image_id}',
                        'size': {
                            'width': { 'magnitude': target_size_pt, 'unit': 'PT' },
                            'height': { 'magnitude': target_size_pt, 'unit': 'PT' }
                        }
                    },
                    'location': {
                        'segmentId': '', # Corps principal du document
                        'index': 1 # Insérer après le premier caractère (souvent un saut de section vide)
                    }
                }
            },
            # Centrer horizontalement le paragraphe contenant l'image
            {
                'updateParagraphStyle': {
                    'range': {
                        'segmentId': '',
                        'startIndex': 1, # L'indice où l'image a été insérée
                        'endIndex': 2  # L'image occupera cet indice après insertion
                    },
                    'paragraphStyle': {
                        'alignment': 'CENTER'
                    },
                    'fields': 'alignment'
                }
            }
            # Note sur le centrage vertical: La Google Docs API rend le centrage vertical complexe
            # pour une image flottante. Pour un positionnement exact, un ajustement manuel
            # dans Google Docs ou l'insertion dans une cellule de tableau peut être nécessaire.
            # L'alignement horizontal est géré ici.
        ]

        # Exécuter les requêtes batch pour mettre à jour le document
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
    page_icon="🔗", # Une petite icône pour l'onglet du navigateur
    layout="centered", # 'centered' ou 'wide'
    initial_sidebar_state="auto"
)

st.title("Générateur de QR Code avec logo LPETH et création Google Docs")
st.markdown("---") # Ligne de séparation

st.write("Bienvenue ! Entrez l'URL de la page pour laquelle vous souhaitez générer un code QR. "
         "Le logo LPETH sera inséré et un nouveau document Google Docs pourra être créé avec le QR code.")

# Champ de saisie pour l'URL
page_url = st.text_input("Veuillez insérer l'URL de la page ici :", "https://www.lpeth.be")

# Nom du fichier de votre logo
LOGO_FILE_NAME = "logo LPETH avril 2016.png" # <--- ASSUREZ-VOUS QUE CE NOM EST EXACT ET QUE LE FICHIER EST PRÉSENT

if page_url:
    st.subheader("Prévisualisation de l'URL :")
    st.code(page_url) # Affiche l'URL dans un bloc de code pour clarté

    st.markdown("### Votre Code QR Généré :")

    # Générer et afficher le code QR avec le logo
    qr_image_final = generate_qr_code_with_logo(page_url, LOGO_FILE_NAME)

    if qr_image_final: # Vérifie si l'image a été générée (pas d'erreur de logo)
        st.image(qr_image_final, caption="Code QR avec logo LPETH. Scannez-moi !", use_column_width=False)
        # La largeur de colonne peut rendre l'image trop grande, mieux vaut la contrôler soi-même.

        st.markdown("---")
        st.markdown("### Options d'exportation :")

        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                label="Télécharger le Code QR (PNG)",
                data=io.BytesIO(qr_image_final.tobytes(format="PNG")), # Assurez-vous que c'est bien formaté
                file_name="code_qr_lpeth.png",
                mime="image/png"
            )
            st.info("Une fois téléchargé, vous pourrez l'insérer dans Google Docs et ajuster sa taille manuellement.")

        with col2:
            if st.button("Créer un Google Docs avec le QR Code"):
                with st.spinner("Création du Google Docs en cours..."):
                    try:
                        docs_service, drive_service = get_google_service()
                        # Convertir l'image PIL en octets pour l'upload
                        buf_for_upload = io.BytesIO()
                        qr_image_final.save(buf_for_upload, format="PNG")
                        byte_im_for_upload = buf_for_upload.getvalue()

                        create_and_insert_qr_to_doc(docs_service, drive_service, byte_im_for_upload, page_url)
                    except Exception as e:
                        st.error(f"Échec de l'initialisation des services Google ou de la création du document : {e}")

else:
    st.warning("Veuillez insérer une URL ci-dessus pour générer le code QR.")

st.markdown("---")
st.markdown("Développé avec ❤️ pour LPETH via Streamlit et Google APIs")