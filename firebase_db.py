import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import logging
import os

logger = logging.getLogger(__name__)

# Initialize Firebase
SERVICE_ACCOUNT_PATH = "teamdl-firebase-adminsdk-fbsvc-e94b44d7c0.json"
DATABASE_URL = "https://teamdl-default-rtdb.firebaseio.com/"

_firebase_app = None

def init_firebase():
    global _firebase_app
    if _firebase_app:
        return
    
    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        _firebase_app = firebase_admin.initialize_app(cred, {
            'databaseURL': DATABASE_URL
        })
        logger.info("Firebase initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")

def is_already_uploaded(title):
    """Checks if the drama title exists in the Firebase database."""
    init_firebase()
    try:
        ref = db.reference('uploaded_titles')
        # To avoid "Index not defined" error, we fetch all and check locally
        # If the number of titles becomes massive, this should be refactored to use keys
        data = ref.get()
        if not data:
            return False
        
        # Check if title exists in the values
        if isinstance(data, dict):
            return title in data.values()
        elif isinstance(data, list):
            return title in data
        return False
    except Exception as e:
        logger.error(f"Error checking title in Firebase: {e}")
        return False

def mark_as_uploaded(title):
    """Saves the title to the Firebase database if not already there."""
    init_firebase()
    try:
        if is_already_uploaded(title):
            return True
            
        ref = db.reference('uploaded_titles')
        ref.push(title)
        logger.info(f"Marked {title} as uploaded in Firebase.")
        return True
    except Exception as e:
        logger.error(f"Error saving title to Firebase: {e}")
        return False
