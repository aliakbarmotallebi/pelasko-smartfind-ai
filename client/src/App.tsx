import { FormEvent, useEffect, useRef, useState } from "react";
import ProductCard from "./components/ProductCard";
import type { ChatItem, WsPayload } from "./types";

function resolveWsUrl(): string {
  const configured = import.meta.env.VITE_WS_URL?.trim();
  if (configured) {
    return configured;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat`;
}

function createId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function App() {
  const [wsUrl, setWsUrl] = useState(resolveWsUrl);
  const [input, setInput] = useState("");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const assistantIdRef = useRef<string | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [items]);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  function connect(): WebSocket {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      return wsRef.current;
    }

    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => setConnected(true);
    socket.onclose = () => {
      setConnected(false);
      setLoading(false);
      assistantIdRef.current = null;
    };
    socket.onerror = () => {
      setItems((prev) => [
        ...prev,
        {
          id: createId(),
          kind: "error",
          content: "اتصال WebSocket برقرار نشد.",
        },
      ]);
      setLoading(false);
    };

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as WsPayload;
      handlePayload(payload);
    };

    return socket;
  }

  function handlePayload(payload: WsPayload) {
    switch (payload.type) {
      case "status":
        setItems((prev) => [
          ...prev,
          {
            id: createId(),
            kind: "status",
            content: payload.content || "در حال پردازش...",
          },
        ]);
        break;

      case "product":
        if (payload.data) {
          setItems((prev) => [
            ...prev,
            { id: createId(), kind: "product", data: payload.data! },
          ]);
        }
        break;

      case "message": {
        const token = payload.content || "";
        if (!assistantIdRef.current) {
          const id = createId();
          assistantIdRef.current = id;
          setItems((prev) => [
            ...prev,
            { id, kind: "assistant", content: token, streaming: true },
          ]);
        } else {
          const currentId = assistantIdRef.current;
          setItems((prev) =>
            prev.map((item) =>
              item.id === currentId && item.kind === "assistant"
                ? { ...item, content: item.content + token }
                : item,
            ),
          );
        }
        break;
      }

      case "error":
        setItems((prev) => [
          ...prev,
          {
            id: createId(),
            kind: "error",
            content: payload.content || "خطای ناشناخته",
          },
        ]);
        setLoading(false);
        assistantIdRef.current = null;
        break;

      case "done":
        if (assistantIdRef.current) {
          const currentId = assistantIdRef.current;
          setItems((prev) =>
            prev.map((item) =>
              item.id === currentId && item.kind === "assistant"
                ? { ...item, streaming: false }
                : item,
            ),
          );
        }
        assistantIdRef.current = null;
        setLoading(false);
        break;
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || loading) return;

    setItems((prev) => [
      ...prev,
      { id: createId(), kind: "user", content: message },
    ]);
    setInput("");
    setLoading(true);
    assistantIdRef.current = null;

    const socket = connect();
    const payload = JSON.stringify({ message });

    if (socket.readyState === WebSocket.OPEN) {
      socket.send(payload);
      return;
    }

    socket.onopen = () => {
      setConnected(true);
      socket.send(payload);
    };
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-6">
      <header className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-white">Pelasko SmartFind</h1>
            <p className="text-sm text-slate-400">کلاینت تست چت فروشگاهی</p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              connected
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-slate-700 text-slate-300"
            }`}
          >
            {connected ? "متصل" : "قطع"}
          </span>
        </div>
        <label className="mt-3 block text-xs text-slate-400">
          WebSocket URL
          <input
            value={wsUrl}
            onChange={(e) => setWsUrl(e.target.value)}
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
            dir="ltr"
          />
        </label>
      </header>

      <main
        ref={listRef}
        className="flex-1 space-y-3 overflow-y-auto rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
      >
        {items.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">
            یک پیام فارسی بفرستید، مثلاً:
            <p className="mt-2 text-slate-300">
              «یه ظرف برای مدرسه میخوام که درب داشته باشه»
            </p>
          </div>
        )}

        {items.map((item) => {
          if (item.kind === "user") {
            return (
              <div key={item.id} className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-sky-600 px-4 py-2 text-sm text-white">
                  {item.content}
                </div>
              </div>
            );
          }

          if (item.kind === "assistant") {
            return (
              <div key={item.id} className="flex justify-end">
                <div className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-bl-md bg-slate-800 px-4 py-3 text-sm leading-7 text-slate-100">
                  {item.content}
                  {item.streaming && (
                    <span className="mr-1 inline-block h-4 w-1 animate-pulse bg-sky-400" />
                  )}
                </div>
              </div>
            );
          }

          if (item.kind === "status") {
            return (
              <p
                key={item.id}
                className="text-center text-xs text-amber-300/90"
              >
                {item.content}
              </p>
            );
          }

          if (item.kind === "error") {
            return (
              <p key={item.id} className="text-center text-xs text-rose-400">
                {item.content}
              </p>
            );
          }

          return (
            <div key={item.id} className="max-w-md">
              <ProductCard product={item.data} />
            </div>
          );
        })}
      </main>

      <form onSubmit={handleSubmit} className="mt-4 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="پیام خود را بنویسید..."
          disabled={loading}
          className="flex-1 rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-sky-500 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-2xl bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
        >
          {loading ? "..." : "ارسال"}
        </button>
      </form>
    </div>
  );
}
