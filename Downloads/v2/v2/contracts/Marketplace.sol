// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/token/common/ERC2981.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/utils/introspection/ERC165Checker.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title Unified Marketplace for ERC721 NFTs with ETH or ERC20 payment, fees & royalties
contract Marketplace is Ownable, ReentrancyGuard {
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
    event FeeRecipientsUpdated(address newPlatform, address newPool);
    event FeeBpsUpdated(uint96 newPlatformFeeBps, uint96 newPoolFeeBps);

    constructor(
        address _pool,
        address _platform,
        uint96 _poolFeeBps,
        uint96 _platformFeeBps
    ) {
        require(_pool != address(0) && _platform != address(0), "Invalid fee recipients");
        require(_poolFeeBps + _platformFeeBps <= 2000, "Total fee too high");
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
        require(price > 0, "Invalid price");
        IERC721 token = IERC721(nft);
        require(token.ownerOf(tokenId) == msg.sender, "Not the owner");
        require(
            token.getApproved(tokenId) == address(this) || token.isApprovedForAll(msg.sender, address(this)),
            "Marketplace not approved"
        );

        listings[nft][tokenId] = Listing({
            seller: msg.sender,
            price: price,
            isERC20: isERC20,
            paymentToken: paymentToken
        });

        emit ItemListed(nft, tokenId, msg.sender, price, isERC20, paymentToken);
    }

    /// @notice Cancel an active listing
    function cancelListing(address nft, uint256 tokenId) external {
        Listing memory listing = listings[nft][tokenId];
        require(listing.seller == msg.sender, "Not the seller");
        delete listings[nft][tokenId];
        emit ItemCanceled(nft, tokenId);
    }

    /// @notice Purchase an NFT using ETH or ERC20
    function buyItem(address nft, uint256 tokenId) external payable nonReentrant {
        Listing memory listing = listings[nft][tokenId];
        require(listing.price > 0, "Not listed");

        delete listings[nft][tokenId];

        uint256 poolAmount = (listing.price * poolFeeBps) / 10000;
        uint256 platformAmount = (listing.price * platformFeeBps) / 10000;
        uint256 sellerAmount = listing.price - poolAmount - platformAmount;

        // Handle royalties if supported
        if (nft.supportsInterface(type(IERC2981).interfaceId)) {
            (address royaltyReceiver, uint256 royaltyAmount) = IERC2981(nft).royaltyInfo(tokenId, listing.price);
            if (royaltyAmount > 0 && royaltyReceiver != address(0)) {
                require(sellerAmount >= royaltyAmount, "Royalty exceeds payout");
                sellerAmount -= royaltyAmount;
                _payout(royaltyReceiver, royaltyAmount, listing);
            }
        }

        _payout(pool, poolAmount, listing);
        _payout(platform, platformAmount, listing);
        _payout(listing.seller, sellerAmount, listing);

        IERC721(nft).safeTransferFrom(listing.seller, msg.sender, tokenId);

        if (!listing.isERC20 && msg.value > listing.price) {
            payable(msg.sender).transfer(msg.value - listing.price);
        }

        emit ItemPurchased(nft, tokenId, msg.sender, listing.price, listing.paymentToken);
    }

    /// @dev Handles both ETH and ERC20 payouts
    function _payout(address to, uint256 amount, Listing memory listing) internal {
        if (amount == 0) return;
        if (listing.isERC20) {
            require(IERC20(listing.paymentToken).transferFrom(msg.sender, to, amount), "ERC20 transfer failed");
        } else {
            payable(to).transfer(amount);
        }
    }

    /// @notice Backward-compatible ERC20 direct purchase logic (no NFT)
    function purchase(address token, address seller, uint256 amount) external nonReentrant {
        uint256 poolAmount = (amount * poolFeeBps) / 10000;
        uint256 platformAmount = (amount * platformFeeBps) / 10000;
        uint256 sellerAmount = amount - poolAmount - platformAmount;

        IERC20 erc20 = IERC20(token);
        require(erc20.transferFrom(msg.sender, seller, sellerAmount), "Seller transfer failed");
        require(erc20.transferFrom(msg.sender, pool, poolAmount), "Pool transfer failed");
        require(erc20.transferFrom(msg.sender, platform, platformAmount), "Platform transfer failed");
    }

    /// @notice Admin: update platform and pool addresses
    function setFeeRecipients(address newPlatform, address newPool) external onlyOwner {
        require(newPlatform != address(0) && newPool != address(0), "Zero address");
        platform = newPlatform;
        pool = newPool;
        emit FeeRecipientsUpdated(newPlatform, newPool);
    }

    /// @notice Admin: update fee percentages
    function setFeeBps(uint96 newPlatformFeeBps, uint96 newPoolFeeBps) external onlyOwner {
        require(newPlatformFeeBps + newPoolFeeBps <= 2000, "Total fee too high");
        platformFeeBps = newPlatformFeeBps;
        poolFeeBps = newPoolFeeBps;
        emit FeeBpsUpdated(newPlatformFeeBps, newPoolFeeBps);
    }

    receive() external payable {}
}
