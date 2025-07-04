from flask import render_template
from . import nft_bp

@nft_bp.route("/", methods=["GET"])
def nft_viewer_home():
    return render_template("nft-viewer.html")
