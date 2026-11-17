import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, Me, post } from "../api";
import { useAuth } from "../auth";

const LOGIN_RE = /^[a-z0-9_.-]{3,32}$/;

export default function Login() {
  const { setMe } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const validate = () => {
    const e: Record<string, string> = {};
    if (mode === "register") {
      if (!LOGIN_RE.test(login.trim().toLowerCase())) e.login = "3–32 символа: латиница, цифры, «_», «.», «-»";
      if (password.length < 6) e.password = "Не короче 6 символов";
      if (password !== password2) e.password2 = "Пароли не совпадают";
    } else {
      if (!login.trim()) e.login = "Введите логин";
      if (!password) e.password = "Введите пароль";
    }
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const me = await post<Me>(`/api/auth/${mode}`, { login, password });
      setMe(me);
      nav("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) setErrors({ [err.field ?? "form"]: err.message });
      else setErrors({ form: "Сервер недоступен" });
    } finally {
      setBusy(false);
    }
  };

  const switchMode = (m: "login" | "register") => {
    setMode(m);
    setErrors({});
  };

  const field = (name: string, label: string, value: string, set: (v: string) => void, type = "text") => (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className={`input mt-1 ${errors[name] ? "border-bad" : ""}`}
        type={type}
        value={value}
        autoComplete={type === "password" ? (mode === "login" ? "current-password" : "new-password") : "username"}
        onChange={(e) => set(e.target.value)}
      />
      {errors[name] && <span className="mt-1 block text-xs text-bad">{errors[name]}</span>}
    </label>
  );

  return (
    <div className="grid h-full place-items-center bg-bg p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent font-mono text-sm font-bold text-white">AI</div>
          <div>
            <div className="text-base font-semibold">ИИ-тьютор</div>
            <div className="text-xs text-muted">Ответы на вопросы по лекциям курса</div>
          </div>
        </div>
        <div className="card p-5">
          <div className="mb-5 grid grid-cols-2 rounded-md bg-panel2 p-1 text-sm">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => switchMode(m)}
                className={`rounded py-1.5 ${mode === m ? "bg-hover text-fg" : "text-muted hover:text-fg"}`}
              >
                {m === "login" ? "Вход" : "Регистрация"}
              </button>
            ))}
          </div>
          <form onSubmit={submit} className="space-y-4" noValidate>
            {field("login", "Логин", login, setLogin)}
            {field("password", "Пароль", password, setPassword, "password")}
            {mode === "register" && field("password2", "Повторите пароль", password2, setPassword2, "password")}
            {errors.form && <div className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">{errors.form}</div>}
            <button className="btn-primary w-full justify-center py-2" disabled={busy}>
              {busy ? "…" : mode === "login" ? "Войти" : "Зарегистрироваться"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
