import { ethers } from "ethers";
import abi from "./abi/MarketplaceUpgradeable.json";

export async function buyItem(provider, contractAddress, nft, tokenId, price) {
  const signer = provider.getSigner();
  const contract = new ethers.Contract(contractAddress, abi, signer);
  const tx = await contract.buyItem(nft, tokenId, { value: ethers.parseEther(price) });
  await tx.wait();
  return tx.hash;
}
