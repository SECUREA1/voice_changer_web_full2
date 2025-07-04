// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "./MarketplaceCore.sol";

/// @title UUPS upgradeable wrapper for MarketplaceCore
contract MarketplaceUpgradeable is Initializable, UUPSUpgradeable, OwnableUpgradeable, MarketplaceCore {
    function initialize(
        address pool_,
        address platform_,
        uint96 poolFeeBps_,
        uint96 platformFeeBps_
    ) public initializer {
        __Ownable_init(msg.sender);
        __UUPSUpgradeable_init();
        _initializeCore(pool_, platform_, poolFeeBps_, platformFeeBps_);
    }

    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}
}
