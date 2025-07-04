// Utility functions for wallet address handling
function hexToBytes(hex){
  if(!hex) return [];
  for (var bytes=[], c=0; c<hex.length; c+=2)
      bytes.push(parseInt(hex.substr(c, 2), 16));
  return bytes;
}
function toBech32(prefix, hex){
  const words = bech32.toWords(Uint8Array.from(hexToBytes(hex)));
  return bech32.encode(prefix, words, 1000, bech32.bech32m);
}
