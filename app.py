import os
import asyncio
import threading
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI
from werkzeug.utils import secure_filename
import pytesseract
from PIL import Image
import fitz  # PyMuPDF for PDFs

import discord
from discord.ext import commands
from pyngrok import ngrok

load_dotenv()

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

# --- Discord bot setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Helpers ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def get_revision_notes(text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are CatchUp.AI, a helpful school AI that summarizes missed lessons into fun revision notes using emojis that match the topic."},
            {"role": "user", "content": f"Summarize this lesson for a student who was absent:\n\n{text}"}
        ]
    )
    return response.choices[0].message.content

# --- Discord helper to DM student ---
async def send_dm_to_student(student_id, topic, notes):
    user = bot.get_user(int(student_id))
    if user:
        try:
            await user.send(f"Hey {user.display_name}! Here's your revision notes for **{topic}**:\n\n{notes}")
            print(f"Sent notes to {user.display_name}")
        except discord.Forbidden:
            print(f"Cannot DM user {user.display_name} (forbidden).")
    else:
        print(f"User with ID {student_id} not found.")

# --- Flask routes ---
@app.route('/members')
def get_members():
    members = app.config.get('discord_members', [])
    return jsonify(members)

@app.route('/', methods=['GET', 'POST'])
def index():
    summary = None
    if request.method == 'POST':
        topic = request.form.get('topic')
        student_id = request.form.get('student_id')
        file = request.files.get('file')

        text_to_summarize = topic + "\n" if topic else ""

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            ext = filename.rsplit('.', 1)[1].lower()
            try:
                if ext == 'pdf':
                    text_to_summarize += extract_text_from_pdf(filepath)
                else:
                    text_to_summarize += pytesseract.image_to_string(Image.open(filepath))
            except Exception as e:
                text_to_summarize += f"\n[Error reading file: {e}]"

        if not student_id:
            summary = "Please select a student to send the notes to."
            return render_template('index.html', summary=summary)

        if text_to_summarize.strip():
            summary = get_revision_notes(text_to_summarize)
            asyncio.run_coroutine_threadsafe(send_dm_to_student(student_id, topic, summary), bot.loop)
        else:
            summary = "Please provide a topic or upload an image/pdf of notes 💀."

    return render_template('index.html', summary=summary)

# --- Discord events ---
@bot.event
async def on_ready():
    print(f"Discord bot logged in as {bot.user}")
    guild = bot.get_guild(GUILD_ID)
    if guild:
        members_list = [{"id": str(m.id), "name": m.display_name} for m in guild.members if not m.bot]
        app.config['discord_members'] = members_list
        print(f"Loaded {len(members_list)} members 💀")
    else:
        print("Guild not found!")

# --- Run Flask + ngrok ---
def run_flask():
    public_url = ngrok.connect(8080)
    print(f"[INFO] ngrok tunnel available at: {public_url}")
    app.run(debug=True, use_reloader=False, port=8080)

def run_discord():
    bot.run(DISCORD_TOKEN)

# --- Main ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_discord()
