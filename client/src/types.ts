export interface ProductData {
  name: string;
  price: number;
  colors: string[];
  specs: string[];
  description: string;
  image: string;
  link: string;
  score: number;
}

export interface WsPayload {
  type: "message" | "product" | "status" | "error" | "done";
  content?: string;
  data?: ProductData;
}

export type ChatItem =
  | { id: string; kind: "user"; content: string }
  | { id: string; kind: "assistant"; content: string; streaming: boolean }
  | { id: string; kind: "status"; content: string }
  | { id: string; kind: "error"; content: string }
  | { id: string; kind: "product"; data: ProductData };
