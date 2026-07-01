# Running the Application with UI

There are two different user interfaces available for this application:

## Option 1: Web-based Corporate Frontend (Recommended)

This option uses a custom web frontend and a FastAPI backend. 

### Step 1: Start the Backend server
1. Open your terminal or command prompt.
2. Navigate to the `Modular_Code` directory:
   ```bash
   cd <project-root>/customer_support_bot/Modular_Code
   ```
3. Start the FastAPI backend server:
   ```bash
   uvicorn api:app --host 0.0.0.0 --port 8000
   ```
   *Make sure you have added your valid Azure credentials to the `.env` file!*

### Step 2: Open the Frontend
Since the frontend is a plain HTML file, there are two ways to open it:
- **Simple way:** Just double-click the `index.html` file in `<project-root>/customer_support_bot/frontend/index.html` to open it in your browser.
- **Using a local server:** You can serve it using Python by navigating to the `frontend` folder and running:
   ```bash
   cd <project-root>/customer_support_bot/frontend
   python -m http.server 8080
   ```
   Then open `http://localhost:8080` in your web browser.

---

## Option 2: Streamlit Prototype UI

If you just want to run the older prototype interface built directly into python using Streamlit:

1. Open your terminal or command prompt.
2. Navigate to the `Modular_Code` directory:
   ```bash
   cd <project-root>/customer_support_bot/Modular_Code
   ```
3. Run the Streamlit application using the following command:
   ```bash
   streamlit run llm_app.py
   ```
4. This will start a local web server, and your default web browser should automatically open displaying the chat interface (usually at `http://localhost:8501`).
