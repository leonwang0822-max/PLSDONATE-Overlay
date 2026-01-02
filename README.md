# PLS DONATE Offline Overlay Manager

A lightweight, local tool to track [PLS DONATE](https://www.roblox.com/games/8737602449/PLS-DONATE) donations in real-time and display a live **Leaderboard** overlay in OBS Studio.

![OBS Preview](preview.png)

## Features

*   **Real-time Tracking**: Connects directly to the PLS DONATE WebSocket API.
*   **Live Leaderboard**: Automatically sorts and displays top donors for the current session.
*   **OBS-Ready**: Text-only, transparent background designed to be added as a Browser Source.
*   **Auto-Save**: Remembers your Roblox User ID and settings between restarts.

## Installation

1.  Ensure you have **Python 3.7+** installed.
2.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

1.  Start the application:
    ```bash
    python app.py
    ```
2.  Open your browser and go to:
    [http://localhost:5000](http://localhost:5000)
3.  Enter your **Roblox User ID** (found in your profile URL) and click **Save & Connect**.
4.  Copy the **Leaderboard Link** provided on the dashboard.
5.  In **OBS Studio**:
    *   Add a new **Browser Source**.
    *   Paste the link.
    *   Set the Width/Height as needed (e.g., 400x600).
    *   The background is transparent by default.

## Leaderboard Format

The leaderboard displays donors in the following format:
```
Username (AmountR$)
```
*Example:* `LeonW (100R$)`
