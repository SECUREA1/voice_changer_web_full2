import sqlite3
from flask import (
    Blueprint, render_template, request, jsonify, current_app, session
)
from flask_login import login_required, current_user

quest_bp = Blueprint(
    "quests",
    __name__,
    url_prefix="/quest-board",
    template_folder="../templates"   # adjust path if your templates folder is elsewhere
)

# ——————— Page Route ———————
@quest_bp.route("/", methods=["GET"])
def show_quests():
    """
    Renders the main Quest Board page.
    """
    return render_template("quest-board.html")


# ——————— API: Claim a Quest ———————
@quest_bp.route("/api/claim", methods=["POST"])
@login_required
def claim_quest():
    data = request.json or {}
    wallet = data.get("wallet")
    chain = data.get("chain")
    reward = int(data.get("reward", 0))

    # verify wallet matches current session
    if wallet != session.get("wallet"):
        return jsonify(status="error", message="Wallet mismatch"), 403

    conn = sqlite3.connect(current_app.config["DB_PATH"])
    c = conn.cursor()

    # ensure the wallet is linked to the logged in user
    c.execute(
        "SELECT 1 FROM users WHERE id=? AND wallet=?",
        (current_user.id, wallet)
    )
    if not c.fetchone():
        conn.close()
        return jsonify(status="error", message="Unauthorized wallet"), 403

    # record reward in leaderboard
    c.execute(
        """
        INSERT INTO leaderboard (wallet, chain, rewards)
        VALUES (?, ?, ?)
        ON CONFLICT(wallet, chain) DO UPDATE SET rewards = rewards + excluded.rewards
        """,
        (wallet, chain, reward)
    )
    conn.commit()
    conn.close()

    return jsonify(status="success", message="Reward recorded.")


# ——————— API: Fetch Top Players ———————
@quest_bp.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    c = conn.cursor()
    c.execute("""
        SELECT wallet, chain, rewards
        FROM leaderboard
        ORDER BY rewards DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()

    return jsonify([
        {"wallet": w, "chain": ch, "rewards": r}
        for w, ch, r in rows
    ])


# —————————— API: Fetch Rewards for Current User ——————————
@quest_bp.route("/api/my-rewards", methods=["GET"])
@login_required
def get_my_rewards():
    wallet = session.get("wallet")
    if not wallet:
        return jsonify(status="error", message="No wallet connected"), 400

    conn = sqlite3.connect(current_app.config["DB_PATH"])
    c = conn.cursor()
    # verify wallet belongs to current user
    c.execute(
        "SELECT 1 FROM users WHERE id=? AND wallet=?",
        (current_user.id, wallet)
    )
    if not c.fetchone():
        conn.close()
        return jsonify(status="error", message="Unauthorized wallet"), 403

    c.execute(
        "SELECT wallet, chain, rewards FROM leaderboard WHERE wallet=?",
        (wallet,)
    )
    rows = c.fetchall()
    conn.close()

    return jsonify([
        {"wallet": w, "chain": ch, "rewards": r}
        for w, ch, r in rows
    ])
