// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title Layered Control NFT with metadata URI
/// @notice Simple ERC-721 used for layered/audio NFTs
contract LayeredControlNFT is ERC721URIStorage, Ownable {
    uint256 private _tokenIds;

    event LayeredMint(address indexed to, uint256 indexed tokenId, string tokenURI);

    constructor(string memory name_, string memory symbol_) ERC721(name_, symbol_) {}

    /// @notice Mint a new token with metadata URI
    function mintLayered(address to, string memory tokenURI) external onlyOwner returns (uint256) {
        _tokenIds += 1;
        uint256 tokenId = _tokenIds;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, tokenURI);
        emit LayeredMint(to, tokenId, tokenURI);
        return tokenId;
    }

    /// @notice Get the latest minted token ID
    function currentTokenId() external view returns (uint256) {
        return _tokenIds;
    }
}
