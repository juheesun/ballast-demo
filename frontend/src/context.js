import { createContext, useContext } from 'react'

export const BidContext = createContext({ bids: [], bidId: null, bid: null, setBidId: () => {}, health: null })
export const useBid = () => useContext(BidContext)
