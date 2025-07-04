// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/token/common/ERC2981.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/utils/introspection/ERC165Checker.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title Core marketplace logic for ERC721 sales with ETH or ERC20 payments
contract MarketplaceCore is ReentrancyGuard {
    using ERC165Checker for address;

    struct Listing {
        address seller;
        uint256 price;
        bool isERC20;
        address paymentToken; // address(0) = ETH
    }

    mapping(address => mapping(uint256 => Listing)) public listings;

    uint96 public poolFeeBps;
    uint96 public platformFeeBps;
    address public pool;
    address public platform;

    event ItemListed(
        address indexed nft,
        uint256 indexed tokenId,
        address seller,
        uint256 price,
        bool isERC20,
        address paymentToken
    );
    event ItemCanceled(address indexed nft, uint256 indexed tokenId);
    event ItemPurchased(
        address indexed nft,
        uint256 indexed tokenId,
        address buyer,
        uint256 price,
        address paymentToken
    );

    function _initializeCore(
        address _pool,
        address _platform,
        uint96 _poolFeeBps,
        uint96 _platformFeeBps
    ) internal {
        require(_pool != address(0) && _platform != address(0), "invalid recipient");
        require(_poolFeeBps + _platformFeeBps <= 2000, "fees too high");
        pool = _pool;
        platform = _platform;
        poolFeeBps = _poolFeeBps;
        platformFeeBps = _platformFeeBps;
    }

    /// @notice List an NFT for sale
    function listItem(
        address nft,
        uint256 tokenId,
        uint256 price,
        bool isERC20,
        address paymentToken
    ) external {
        require(price > 0, "invalid price");
        IERC721 token = IERC721(nft);
        require(token.ownerOf(tokenId) == msg.sender, "not owner");
        require(
            token.getApproved(tokenId) == address(this) || token.isApprovedForAll(msg.sender, address(this)),
            "not approved"
        );

        listings[nft][tokenId] = Listing(msg.sender, price, isERC20, paymentToken);
        emit ItemListed(nft, tokenId, msg.sender, price, isERC20, paymentToken);
    }

    /// @notice Cancel an active listing
    function cancelListing(address nft, uint256 tokenId) external {
        Listing memory listing = listings[nft][tokenId];
        require(listing.seller == msg.sender, "not seller");
        delete listings[nft][tokenId];
        emit ItemCanceled(nft, tokenId);
    }

    /// @notice Purchase an NFT
    function buyItem(address nft, uint256 tokenId) external payable nonReentrant {
        Listing memory listing = listings[nft][tokenId];
        require(listing.price > 0, "not listed");
        delete listings[nft][tokenId];

        uint256 poolCut = (listing.price * poolFeeBps) / 10000;
        uint256 platformCut = (listing.price * platformFeeBps) / 10000;
        uint256 remaining = listing.price - poolCut - platformCut;

        // Pay royalty if supported
        if (nft.supportsInterface(type(IERC2981).interfaceId)) {
            (address receiver, uint256 royaltyAmount) = IERC2981(nft).royaltyInfo(tokenId, listing.price);
            if (royaltyAmount > 0 && receiver != address(0)) {
                require(remaining >= royaltyAmount, "royalty exceeds payout");
                remaining -= royaltyAmount;
                _payout(receiver, royaltyAmount, listing);
            }
        }

        _payout(pool, poolCut, listing);
        _payout(platform, platformCut, listing);
        _payout(listing.seller, remaining, listing);

        IERC721(nft).safeTransferFrom(listing.seller, msg.sender, tokenId);

        if (!listing.isERC20 && msg.value > listing.price) {
            payable(msg.sender).transfer(msg.value - listing.price);
        }

        emit ItemPurchased(nft, tokenId, msg.sender, listing.price, listing.paymentToken);
    }

    /// @dev Payout helper for ETH or ERC20
    function _payout(address to, uint256 amount, Listing memory listing) internal {
        if (amount == 0) return;
        if (listing.isERC20) {
            require(IERC20(listing.paymentToken).transferFrom(msg.sender, to, amount), "ERC20 transfer failed");
        } else {
            payable(to).transfer(amount);
        }
    }

    /// @notice Direct ERC20 payment split (no listing)
    function purchase(address token, address seller, uint256 amount) external nonReentrant {
        uint256 poolCut = (amount * poolFeeBps) / 10000;
        uint256 platformCut = (amount * platformFeeBps) / 10000;
        uint256 sellerAmount = amount - poolCut - platformCut;

        IERC20 erc20 = IERC20(token);
        require(erc20.transferFrom(msg.sender, seller, sellerAmount), "seller transfer failed");
        require(erc20.transferFrom(msg.sender, pool, poolCut), "pool transfer failed");
        require(erc20.transferFrom(msg.sender, platform, platformCut), "platform transfer failed");
    }
}

