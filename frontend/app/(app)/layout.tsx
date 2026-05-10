import { AppChrome } from "../../components/AppChrome";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppChrome>{children}</AppChrome>;
}
