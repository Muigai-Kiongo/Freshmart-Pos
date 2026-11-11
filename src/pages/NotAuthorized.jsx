import { useNavigate } from "react-router-dom";

const NotAuthorized = () => {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-dvh items-center justify-center bg-brand-50 p-6">
      <div className="text-center">
        <h1 className="text-9xl font-extrabold leading-none text-red-500">403</h1>

        <div className="mx-auto my-4 h-1 w-16 rounded-full bg-red-400" />

        <h2 className="mb-2 text-2xl font-bold text-gray-800">Access Denied</h2>
        <p className="mb-8 text-gray-500">
          You don't have permission to view this page.
        </p>

        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="rounded-lg border border-gray-300 px-5 py-2 text-sm text-gray-600 transition hover:bg-gray-200"
          >
            ← Go Back
          </button>
          <button
            onClick={() => navigate("/")}
            className="rounded-lg bg-brand-700 px-5 py-2 text-sm font-semibold text-white transition hover:bg-brand-800"
          >
            Go Home
          </button>
        </div>
      </div>
    </div>
  );
};

export default NotAuthorized;
