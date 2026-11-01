# 🌐 100% FREE 24/7 CLOUD HOSTING GUIDE (LAPTOP CAN BE OFF)

To run the game online so your laptop doesn't need to stay on, you can host it for free on **Render** (via GitHub) or **Hugging Face Spaces** (Direct Upload, no GitHub needed).

Both options support real-time WebSockets and provide a permanent HTTPS link!

---

## 🌟 OPTION A: Render.com (Recommended)

Render gives you a permanent URL like `https://hostel-manhunt.onrender.com` that stays online 24/7.

### Step 1: Upload to GitHub (No Git terminal required)
1. Go to [github.com](https://github.com) (sign in or create a free account).
2. Click the **"+"** button at top right -> **New repository**.
3. Name it `campus-manhunt` -> Select **Public** -> Click **Create repository**.
4. On the next screen, click the link that says: **"uploading an existing file"**.
5. Drag and drop all the files from your `campus-manhunt` folder (or unzip `campus-manhunt-deploy.zip` and drag them in):
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `render.yaml`
   - `Dockerfile`
   - `static/` folder
6. Scroll down and click **Commit changes**.

### Step 2: Deploy on Render
1. Go to [render.com](https://render.com) and sign in with your GitHub account.
2. Click **New +** (top right) -> **Web Service**.
3. Choose your `campus-manhunt` repository and click **Connect**.
4. Set the following settings (Render usually fills these automatically):
   - **Name**: `hostel-manhunt` (or whatever you like)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
5. Click **Create Web Service**!

Render will build and launch your game in about 1-2 minutes. Once finished, you will see your live public URL (e.g. `https://hostel-manhunt.onrender.com`).

---

## 🚀 OPTION B: Hugging Face Spaces (No GitHub Needed!)

If you don't want to create a GitHub repo, Hugging Face lets you drag-and-drop files directly in the browser.

1. Go to [huggingface.co](https://huggingface.co) and create a free account.
2. Click your profile icon at top right -> **New Space**.
3. Fill in:
   - **Space name**: `hostel-manhunt`
   - **License**: `mit` or `apache-2.0`
   - **Space SDK**: Select **Docker** -> choose **Blank**.
   - **Space Hardware**: Free
4. Click **Create Space**.
5. Click the **Files** tab -> Click **Add file** -> **Upload files**.
6. Drag in the contents of `campus-manhunt` (`Dockerfile`, `requirements.txt`, `app.py`, and `static/` folder).
7. Click **Commit changes to main**.

Hugging Face will build the Docker container and display your live game at:
`https://<your-username>-hostel-manhunt.hf.space`

---

## 🎉 Done!
Now your game runs in the cloud permanently. You can turn off your laptop, close your browser, and play with your hostel squad anytime, anywhere!
