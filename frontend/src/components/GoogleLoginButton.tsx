import { useEffect, useRef, useState } from "react";

interface GoogleCredentialResponse {
  credential: string;
}

interface GoogleButtonOptions {
  theme: "outline";
  size: "medium";
  shape: "pill";
  text: "signin_with";
  locale: "ko";
  width: number;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }): void;
          renderButton(parent: HTMLElement, options: GoogleButtonOptions): void;
          disableAutoSelect(): void;
        };
      };
    };
  }
}

interface GoogleLoginButtonProps {
  clientId: string;
  disabled?: boolean;
  onCredential: (credential: string) => void | Promise<void>;
  onLoadError: () => void;
}

const GOOGLE_SCRIPT_ID = "google-identity-services";
const GOOGLE_SCRIPT_URL = "https://accounts.google.com/gsi/client?hl=ko";

export default function GoogleLoginButton({
  clientId,
  disabled = false,
  onCredential,
  onLoadError,
}: GoogleLoginButtonProps) {
  const buttonRef = useRef<HTMLDivElement>(null);
  const callbackRef = useRef(onCredential);
  const errorCallbackRef = useRef(onLoadError);
  const [rendered, setRendered] = useState(false);

  callbackRef.current = onCredential;
  errorCallbackRef.current = onLoadError;

  useEffect(() => {
    let cancelled = false;

    const render = () => {
      if (cancelled || !window.google || !buttonRef.current) return;
      buttonRef.current.replaceChildren();
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (response) => void callbackRef.current(response.credential),
      });
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: "outline",
        size: "medium",
        shape: "pill",
        text: "signin_with",
        locale: "ko",
        width: 190,
      });
      setRendered(true);
    };

    const existingScript = document.getElementById(GOOGLE_SCRIPT_ID) as HTMLScriptElement | null;
    if (window.google) {
      render();
    } else if (existingScript) {
      existingScript.addEventListener("load", render, { once: true });
      existingScript.addEventListener("error", () => errorCallbackRef.current(), { once: true });
    } else {
      const script = document.createElement("script");
      script.id = GOOGLE_SCRIPT_ID;
      script.src = GOOGLE_SCRIPT_URL;
      script.async = true;
      script.onload = render;
      script.onerror = () => errorCallbackRef.current();
      document.head.appendChild(script);
    }

    return () => {
      cancelled = true;
    };
  }, [clientId]);

  return (
    <div
      className={`relative min-h-8 min-w-[190px] ${disabled ? "pointer-events-none opacity-50" : ""}`}
      aria-busy={!rendered || disabled}
    >
      {!rendered && (
        <span className="absolute inset-0 flex items-center justify-center rounded-full border border-black/10 bg-white text-xs text-stone-500">
          Google 로그인 불러오는 중
        </span>
      )}
      <div ref={buttonRef} />
    </div>
  );
}
