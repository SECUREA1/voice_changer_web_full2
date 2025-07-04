// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Royalty.sol";

contract RoyaltyNFT is ERC721Royalty {
    uint256 private _tokenIds;

    constructor() ERC721("RoyaltyNFT", "RNFT") {}

    function mint(address to, address royaltyReceiver, uint96 feeNumerator) external returns (uint256) {
        _tokenIds += 1;
        _mint(to, _tokenIds);
        _setTokenRoyalty(_tokenIds, royaltyReceiver, feeNumerator);
        return _tokenIds;
    }
}
