import os
import wave
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from pydub import AudioSegment

from google.cloud import speech
from google import genai

PROJECT_ID = "eikon-dev-ai-team"
LOCATION = "us-central1"

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'ogg', 'webm', 'flac'}

app = Flask(__name__, static_url_path='/static')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Logging configuration
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

# Set up a file handler that rotates logs, keeping 5 backup files of 5MB each.
file_handler = RotatingFileHandler('app.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Also log to the console (useful for development).
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Add handlers to the Flask app's logger.
# We do this instead of configuring the root logger to avoid capturing logs from libraries.
app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
app.logger.setLevel(logging.INFO)

# This removes the default Flask handler to avoid duplicate logs in the console.
app.logger.removeHandler(app.logger.handlers[0])

app.logger.info("Flask application starting up...")

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_to_wav(source_path, target_path):
    """Converts any audio file to the required WAV format for Google Speech API."""
    app.logger.info(f"Converting {source_path} to WAV format...")
    audio = AudioSegment.from_file(source_path)
    audio = audio.set_channels(1)
    audio.export(target_path, format="wav", codec="pcm_s16le")
    app.logger.info(f"Successfully converted to {target_path}")

def transcribe_with_diarization(wav_file_path):
    """
    Transcribes a local WAV  audio file using speaker diarization.
    """
    client = speech.SpeechClient()

    with wave.open(wav_file_path, "rb") as wave_file:
        frame_rate = wave_file.getframerate()
        channels = wave_file.getnchannels()

    with open(wav_file_path, "rb") as audio_file:
        content = audio_file.read()

    audio = speech.RecognitionAudio(content=content)

    diarization_config = speech.SpeakerDiarizationConfig(
        enable_speaker_diarization=True,
        min_speaker_count=2,
        max_speaker_count=10,
    )

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=frame_rate, 
        language_code="id-ID",
        diarization_config=diarization_config,
        audio_channel_count=channels, 
        enable_automatic_punctuation=True,
    )

    app.logger.info("Sending request to Google Speech-to-Text API...")
    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=300) # Set a timeout for the operation
    app.logger.info("Response received from Speech-to-Text API.")

    if not response.results or not response.results[-1].alternatives:
        return None 

    result = response.results[-1]
    words_info = result.alternatives[0].words

    # Build the readable transcript string
    transcript_parts = []
    current_speaker_tag = None
    
    for word_info in words_info:
        if word_info.speaker_tag != current_speaker_tag:
            if current_speaker_tag is not None:
                transcript_parts.append("\n")
            current_speaker_tag = word_info.speaker_tag
            transcript_parts.append(f"Speaker {current_speaker_tag}: ")
        transcript_parts.append(word_info.word + " ")

    # Join all parts into a single string
    full_transcript = "".join(transcript_parts)
    
    # Clean up spacing around punctuation for better readability
    return full_transcript.replace(" .", ".").replace(" ,", ",").replace(" ?", "?").strip()

def analyze_conversation_with_gemini(transcript: str, project_id: str, location: str):
    """
    Summarizes a conversation and extracts key points using the Gemini API.

    Args:
        transcript (str): The conversation transcript text.
        api_key (str): Your Google Gemini API key.

    Returns:
        str: A formatted string containing the summary and key points, 
             or an error message.
    """
    try:
        # Configure the Gemini API with your key
        genai_client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location)
        
        # Create the model
        model="gemini-2.0-flash-001"

        prompt = f"""
        Analyze the following transcript of a conversation between a doctor (Dok) and a patient (Bapak Budi) in Bahasa Indonesia.

        Your tasks are:
        1.  Provide a concise summary of the entire conversation in Bahasa Indonesia.
        2.  Extract and list the most important points, categorizing them clearly.

        Use the following Markdown format for your response:

        **Ringkasan Singkat:**
        [Your summary here in one paragraph]

        **Poin-Poin Penting:**
        - **Keluhan Pasien:** [List the patient's symptoms]
        - **Diagnosis Dokter:** [State the doctor's diagnosis]
        - **Rekomendasi & Resep:** [List the doctor's advice and treatment plan]
        - **Instruksi Tindak Lanjut:** [State the follow-up instructions]

        Here is the transcript:
        ---
        {transcript}
        ---
        """

        app.logger.info("Sending request to Vertex AI Gemini...")
        response = genai_client.models.generate_content(
                                                model=model,
                                                contents=prompt
                                                )
        app.logger.info("Response from Gemini received.")
        return response.text

    except Exception as e:
        app.logger.error(f"Error during Gemini analysis: {e}", exc_info=True)
        return f"An error occurred: {e}"
    
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/analyze', methods=['POST'])
def analyze_audio():
    if 'audioFile' not in request.files:
        app.logger.warning("Analyze request received without 'audioFile' part.")
        return jsonify({"error": "No audio file part"}), 400
    
    file = request.files['audioFile']
    if file.filename == '' or not allowed_file(file.filename):
        app.logger.warning(f"Analyze request with invalid file: {file.filename}")
        return jsonify({"error": "No selected file or file type not allowed"}), 400

    filename = secure_filename(file.filename)
    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    wav_filename = os.path.splitext(filename)[0] + '.wav'
    wav_path = os.path.join(app.config['UPLOAD_FOLDER'], wav_filename)
    
    app.logger.info(f"Received file for analysis: {filename}")

    try:
        file.save(upload_path)
        
        app.logger.info("Step 1: Converting uploaded audio to WAV format.")
        convert_to_wav(upload_path, wav_path)
        
        app.logger.info("Step 2: Transcribing the WAV file.")
        transcript = transcribe_with_diarization(wav_path)
        if transcript is None:
            app.logger.error("Transcription failed. The audio might be silent or too noisy.")
            return jsonify({"error": "Transcription failed. The audio might be silent or too noisy."}), 500
        app.logger.info("Transcription successful.")

        app.logger.info("Step 3: Analyzing transcript with Gemini.")
        analysis = analyze_conversation_with_gemini(transcript, PROJECT_ID, LOCATION)
        app.logger.info(f"Successfully processed and returning analysis for {filename}")
        
        return jsonify({"transcript": transcript, "analysis": analysis})
    
    except Exception as e:
        app.logger.error(f"An unhandled error occurred in /analyze endpoint for file {filename}", exc_info=True)
        return jsonify({"error": f"An internal server error occurred. Check server logs for details."}), 500
    
    finally:
        app.logger.info(f"Cleaning up temporary files: {upload_path}, {wav_path}")
        if os.path.exists(upload_path):
            os.remove(upload_path)
        if os.path.exists(wav_path):
            os.remove(wav_path)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)