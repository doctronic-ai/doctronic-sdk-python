"""Public types: the contract's models, chat stream events, and webhook events.

Models use snake_case attributes with the contract's camelCase names as aliases, so
`model.model_dump(by_alias=True)` gives the wire shape back.
"""

from ._generated.models import (
    AddressResponse,
    AppointmentAPIStatus,
    AppointmentResponse,
    AppointmentResultPendingResponse,
    AppointmentResultPharmacy,
    AppointmentResultPharmacyAddress,
    AppointmentResultPrescription,
    AppointmentResultResponse,
    AppointmentWaitingRoomUnavailableData,
    ArtifactContent,
    ArtifactResponse,
    AsapAppointmentResponse,
    AvailableSlotsResponse,
    ChatResponse,
    ClinicianNoteArtifactResponse,
    InsufficientScopeData,
    LocationSchema,
    LongSummaryArtifactResponse,
    MessageResponse,
    PageAppointmentResponse,
    PageChatResponse,
    PageMessageResponse,
    Pharmacy,
    PharmacyAddress,
    PharmacySearchResponse,
    Role,
    ScheduledAppointmentResponse,
    Scope,
    Sex,
    ShortSummaryArtifactResponse,
    SoapNoteArtifactResponse,
    State,
    UserCreatedResponse,
    ValidationErrorDetail,
)
from ._streaming import (
    AiConsultationCompleteEvent,
    ChatStreamEvent,
    ConsultationArtifacts,
    ConversationEndEvent,
    ConversationOfftopicEvent,
    FinalMessages,
    GuardianEvent,
    KnownChatStreamEvent,
    MessageContentEvent,
    MessageStartEvent,
    MessageStopEvent,
    SkillCodeCtaEvent,
    StreamedMessage,
    StreamErrorEvent,
    UnknownChatStreamEvent,
)
from ._types import LocationParam
from .webhooks import (
    AppointmentCallEndedData,
    AppointmentCallEndedEvent,
    AppointmentPractitionerJoinedData,
    AppointmentPractitionerJoinedEvent,
    AppointmentWaitingRoomReadyData,
    AppointmentWaitingRoomReadyEvent,
    ArtifactReadyData,
    ArtifactReadyEvent,
    KnownWebhookEvent,
    UnknownWebhookEvent,
    WebhookEvent,
)

# Short names for the contract's models, the same as the TypeScript SDK's.
User = UserCreatedResponse
Chat = ChatResponse
ChatPage = PageChatResponse
ChatMessage = MessageResponse
ChatMessagePage = PageMessageResponse
Appointment = AppointmentResponse
AppointmentStatus = AppointmentAPIStatus
AppointmentPage = PageAppointmentResponse
ScheduledAppointment = ScheduledAppointmentResponse
AsapAppointment = AsapAppointmentResponse
AppointmentResult = AppointmentResultResponse
AvailableSlots = AvailableSlotsResponse
UsState = State
Address = AddressResponse
PharmacySearchResults = PharmacySearchResponse
Artifact = ArtifactResponse

__all__ = [
    "Address",
    "AddressResponse",
    "AiConsultationCompleteEvent",
    "Appointment",
    "AppointmentAPIStatus",
    "AppointmentCallEndedData",
    "AppointmentCallEndedEvent",
    "AppointmentPage",
    "AppointmentPractitionerJoinedData",
    "AppointmentPractitionerJoinedEvent",
    "AppointmentResponse",
    "AppointmentResult",
    "AppointmentResultPendingResponse",
    "AppointmentResultPharmacy",
    "AppointmentResultPharmacyAddress",
    "AppointmentResultPrescription",
    "AppointmentResultResponse",
    "AppointmentStatus",
    "AppointmentWaitingRoomReadyData",
    "AppointmentWaitingRoomReadyEvent",
    "AppointmentWaitingRoomUnavailableData",
    "Artifact",
    "ArtifactContent",
    "ArtifactReadyData",
    "ArtifactReadyEvent",
    "ArtifactResponse",
    "AsapAppointment",
    "AsapAppointmentResponse",
    "AvailableSlots",
    "AvailableSlotsResponse",
    "Chat",
    "ChatMessage",
    "ChatMessagePage",
    "ChatPage",
    "ChatResponse",
    "ChatStreamEvent",
    "ClinicianNoteArtifactResponse",
    "ConsultationArtifacts",
    "ConversationEndEvent",
    "ConversationOfftopicEvent",
    "FinalMessages",
    "GuardianEvent",
    "InsufficientScopeData",
    "KnownChatStreamEvent",
    "KnownWebhookEvent",
    "LocationParam",
    "LocationSchema",
    "LongSummaryArtifactResponse",
    "MessageContentEvent",
    "MessageResponse",
    "MessageStartEvent",
    "MessageStopEvent",
    "PageAppointmentResponse",
    "PageChatResponse",
    "PageMessageResponse",
    "Pharmacy",
    "PharmacyAddress",
    "PharmacySearchResponse",
    "PharmacySearchResults",
    "Role",
    "ScheduledAppointment",
    "ScheduledAppointmentResponse",
    "Scope",
    "Sex",
    "ShortSummaryArtifactResponse",
    "SkillCodeCtaEvent",
    "SoapNoteArtifactResponse",
    "State",
    "StreamErrorEvent",
    "StreamedMessage",
    "UnknownChatStreamEvent",
    "UnknownWebhookEvent",
    "UsState",
    "User",
    "UserCreatedResponse",
    "ValidationErrorDetail",
    "WebhookEvent",
]
