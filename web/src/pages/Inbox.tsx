import FeedbackList from "./FeedbackList";

/** The feedback of every site the signed-in user can see, in one list. */
export default function Inbox() {
  return (
    <>
      <div className="page-head"><h1>Inbox</h1></div>
      <FeedbackList />
    </>
  );
}
