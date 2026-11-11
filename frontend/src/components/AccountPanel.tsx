import { signInUrl } from "../api/client";
import { SIGN_IN_PROVIDERS } from "../api/types";
import type { Account } from "../api/types";

type Props = {
  account: Account | null;
  disabled: boolean;
  onSignOut: () => void;
};

export function AccountPanel({ account, disabled, onSignOut }: Props) {
  if (account === null) {
    return <p className="hint account">Checking whether you are signed in…</p>;
  }

  if (account.user === null) {
    return (
      <section className="card account">
        <h2>Sign in to start</h2>
        <p className="hint">
          Have a look around — signing in is only needed to start an interview. Each account
          gets a few questions a day, on Claude.
        </p>
        <div className="sign-in">
          {account.providers.map((provider) => (
            <a key={provider} className="button" href={signInUrl(provider)}>
              Sign in with {SIGN_IN_PROVIDERS[provider]}
            </a>
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="account signed-in">
      <p>
        Signed in as <strong>{account.user.name}</strong>
        {account.questions_left !== null && (
          <span className="hint">
            {" "}
            · {account.questions_left} {account.questions_left === 1 ? "question" : "questions"}{" "}
            left today
          </span>
        )}
      </p>
      <button type="button" className="secondary" onClick={onSignOut} disabled={disabled}>
        Sign out
      </button>
    </div>
  );
}
