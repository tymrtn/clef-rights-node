import { safeStorageGet } from "./storage";

type Locale = "en" | "es";

const STRINGS: Record<Locale, Record<string, string>> = {
  en: {
    "gate.title": "Sign in (demo)",
    "gate.owner": "Owner / Org email",
    "gate.user": "Your email",
    "gate.continue": "Continue",
    "gate.demoWarning": "Demo identities are not credentials.",
  },
  es: {
    "gate.title": "Iniciar sesión (demo)",
    "gate.owner": "Correo de la organización",
    "gate.user": "Tu correo",
    "gate.continue": "Continuar",
  },
};

export function getLocale(): Locale {
  const raw = (safeStorageGet("local", "rc.locale") || "en").toLowerCase();
  return raw === "es" ? "es" : "en";
}

export function t(key: string): string {
  const locale = getLocale();
  return STRINGS[locale][key] || STRINGS.en[key] || key;
}
